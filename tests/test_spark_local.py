"""Ejecuta la transformación en una sesión local de Spark y la compara con la
implementación de referencia en Python puro.

Es la prueba que responde a "¿hace Spark lo mismo que dice la especificación?".
Si PySpark no está instalado, la suite se salta sin fallar: el resto de tests
no debe depender de tener un Spark en la máquina.

    tests/venv/bin/python -m unittest tests.test_spark_local -v
"""

import pathlib
import shutil
import sys
import tempfile
import unittest
from datetime import date

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src" / "glue"))

try:
    from pyspark.sql import SparkSession
except ImportError:  # pragma: no cover
    SparkSession = None

DATOS = pathlib.Path(__file__).resolve().parent / "datos"
DIA = date(2024, 3, 1)


@unittest.skipIf(SparkSession is None, "pyspark no instalado")
@unittest.skipIf(not DATOS.exists(), "faltan los ficheros de ejemplo en tests/datos")
class SparkContraReferencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.appName("prueba-curated")
            .master("local[1]")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

        import transformacion

        cls.filas = transformacion.transformar(cls.spark, str(DATOS), DIA).cache()
        cls.informe = transformacion.revisar(cls.filas, DIA)
        cls.transformacion = transformacion

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def referencia(self):
        """Las mismas filas calculadas sin Spark."""
        import json

        import parseo

        def cargar(fuente):
            ruta = (
                DATOS / f"fuente={fuente}" / f"anio={DIA.year:04d}"
                / f"mes={DIA.month:02d}" / f"dia={DIA.day:02d}" / "datos.json"
            )
            return json.loads(ruta.read_text(encoding="utf-8"))

        return parseo.unir(
            parseo.demanda(cargar("ree_demanda")),
            parseo.precio(cargar("ree_precio")),
            parseo.temperatura(cargar("clima_temperatura")),
        )

    @staticmethod
    def _marcas(df):
        """Formatea el instante dentro de Spark, no al recogerlo.

        `collect()` devuelve los TimestampType convertidos a la zona horaria
        del driver y sin tzinfo, no en la zona de sesion. Comparar esos
        objetos contra UTC da una diferencia de una hora que no existe en el
        dato. Formatear en Spark elimina la ambiguedad.
        """
        from pyspark.sql import functions as F

        return df.withColumn("marca", F.date_format("momento_utc", "yyyy-MM-dd HH:mm:ss"))

    def test_spark_produce_las_mismas_filas_que_la_referencia(self):
        esperadas = self.referencia()
        obtenidas = sorted(
            (r.asDict() for r in self._marcas(self.filas).collect()), key=lambda f: f["marca"]
        )

        self.assertEqual(len(obtenidas), len(esperadas))
        for got, exp in zip(obtenidas, esperadas):
            self.assertEqual(got["marca"], exp["momento_utc"].strftime("%Y-%m-%d %H:%M:%S"))
            for columna in ("demanda_mw", "precio_pvpc_eur_mwh", "precio_spot_eur_mwh", "temperatura_c"):
                if exp[columna] is None:
                    self.assertIsNone(got[columna], columna)
                else:
                    self.assertAlmostEqual(got[columna], exp[columna], places=6, msg=columna)

    def test_el_dia_sale_completo_y_sin_errores(self):
        self.assertEqual(self.informe["filas"], 24)
        self.assertEqual(self.informe["errores"], [])
        self.assertEqual(self.informe["avisos"], [])
        self.assertEqual(self.informe["nulos_demanda_mw"], 0)
        self.assertEqual(self.informe["nulos_temperatura_c"], 0)

    def test_el_desfase_horario_es_el_de_invierno(self):
        """La medianoche local del 1 de marzo es 23:00 UTC del 29 de febrero.

        Si se hubiera usado el utc_offset_seconds de Open-Meteo, seria 22:00.
        """
        primera = self._marcas(self.filas).orderBy("momento_utc").first()
        self.assertEqual(primera["marca"], "2024-02-29 23:00:00")

    def test_escribe_parquet_con_particiones_de_dos_digitos(self):
        destino = tempfile.mkdtemp(prefix="curated-")
        try:
            (
                self.transformacion.con_particiones(self.filas)
                .repartition(1)
                .write.mode("overwrite")
                .partitionBy("anio", "mes", "dia")
                .parquet(destino)
            )
            rutas = [str(p) for p in pathlib.Path(destino).rglob("*.parquet")]
            self.assertTrue(rutas, "no se escribio ningun parquet")
            self.assertIn("anio=2024/mes=03/dia=01", rutas[0])

            leido = self.spark.read.parquet(destino)
            self.assertEqual(leido.count(), 24)
            self.assertIn("momento_local", leido.columns)
        finally:
            shutil.rmtree(destino, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
