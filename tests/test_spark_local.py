"""Ejecuta la transformación en una sesión local de Spark y la compara con la
implementación de referencia en Python puro.

Es la prueba que responde a "¿hace Spark lo mismo que dice la especificación?".
Si PySpark no está instalado, la suite se salta sin fallar: el resto de tests
no debe depender de tener un Spark en la máquina.

    tests/venv/bin/python -m unittest tests.test_spark_local -v
"""

import json
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
ATRASA = date(2024, 10, 27)  # 25 horas locales: la hora repetida de octubre

_SESION = None


def sesion():
    """Una sola sesión para todas las clases: levantar Spark es lo caro."""
    global _SESION
    if _SESION is None:
        _SESION = (
            SparkSession.builder.appName("prueba-curated")
            .master("local[1]")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        _SESION.sparkContext.setLogLevel("ERROR")
    return _SESION


@unittest.skipIf(SparkSession is None, "pyspark no instalado")
@unittest.skipIf(not DATOS.exists(), "faltan los ficheros de ejemplo en tests/datos")
class SparkContraReferencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = sesion()

        import transformacion

        cls.filas = transformacion.transformar(cls.spark, str(DATOS), DIA).cache()
        cls.informe = transformacion.revisar(cls.filas, DIA)
        cls.transformacion = transformacion

    def referencia(self):
        """Las mismas filas calculadas sin Spark."""
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
            parseo.temperatura(cargar("clima_temperatura"), DIA),
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

    def test_el_dia_empieza_donde_empieza_el_dia_local(self):
        """La medianoche local del 1 de marzo es 23:00 UTC del 29 de febrero."""
        primera = self._marcas(self.filas).orderBy("momento_utc").first()
        self.assertEqual(primera["marca"], "2024-02-29 23:00:00")

    def test_la_temperatura_no_va_corrida_respecto_a_la_fuente(self):
        """El test que le faltaba a la fase: contrastar contra el JSON crudo.

        La suite comparaba Spark contra la referencia en Python, y las dos
        aplicaban la misma regla equivocada, asi que salia verde con el dato
        desplazado una hora. Esto compara contra lo que dice la fuente.

        Open-Meteo se pide con timezone=UTC, de modo que la etiqueta del
        payload es directamente el instante que debe aparecer en curated.
        """
        ruta = (
            DATOS / "fuente=clima_temperatura" / f"anio={DIA.year:04d}"
            / f"mes={DIA.month:02d}" / f"dia={DIA.day:02d}" / "datos.json"
        )
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertEqual(crudo["utc_offset_seconds"], 0, "el fichero de ejemplo no esta en UTC")

        origen = dict(zip(crudo["hourly"]["time"], crudo["hourly"]["temperature_2m"]))
        obtenidas = {
            r["marca"]: r["temperatura_c"] for r in self._marcas(self.filas).collect()
        }

        for marca, temperatura in obtenidas.items():
            etiqueta = marca.replace(" ", "T")[:16]
            self.assertAlmostEqual(
                temperatura, origen[etiqueta], places=6,
                msg=f"{marca} deberia traer la temperatura que la fuente pone en {etiqueta}",
            )

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


@unittest.skipIf(SparkSession is None, "pyspark no instalado")
@unittest.skipIf(not DATOS.exists(), "faltan los ficheros de ejemplo en tests/datos")
class SparkElDiaQueAtrasa(unittest.TestCase):
    """27 de octubre de 2024 en Spark: 25 horas y una hora local repetida.

    Es el dia mas dificil del ano para este pipeline y el que la ingesta
    anterior no podia procesar: pedida en hora local, Open-Meteo devolvia 24
    etiquetas a desfase fijo y una de las dos 02:00 se perdia.
    """

    @classmethod
    def setUpClass(cls):
        import transformacion

        cls.transformacion = transformacion
        cls.filas = transformacion.transformar(sesion(), str(DATOS), ATRASA).cache()
        cls.informe = transformacion.revisar(cls.filas, ATRASA)

    def test_salen_las_25_horas_sin_errores(self):
        self.assertEqual(self.informe["filas"], 25)
        self.assertEqual(self.informe["filas_esperadas"], 25)
        self.assertEqual(self.informe["errores"], [])
        self.assertEqual(self.informe["avisos"], [])

    def test_ninguna_hora_queda_sin_temperatura(self):
        self.assertEqual(self.informe["nulos_temperatura_c"], 0)
        self.assertEqual(self.informe["nulos_demanda_mw"], 0)

    def test_los_25_instantes_son_distintos(self):
        self.assertEqual(self.informe["filas"], self.informe["instantes"])

    def test_la_hora_repetida_son_dos_instantes_separados_una_hora(self):
        from pyspark.sql import functions as F

        marcas = [
            r["marca"]
            for r in (
                self.filas.withColumn(
                    "marca", F.date_format("momento_utc", "yyyy-MM-dd HH:mm:ss")
                )
                .orderBy("momento_utc")
                .collect()
            )
        ]
        # 02:00 y 03:00 UTC del 27 son las dos 02:00 locales de Madrid.
        self.assertIn("2024-10-27 00:00:00", marcas)
        self.assertIn("2024-10-27 01:00:00", marcas)
        self.assertEqual(marcas[0], "2024-10-26 22:00:00")
        self.assertEqual(marcas[-1], "2024-10-27 22:00:00")

    def test_spark_coincide_con_la_referencia_en_python(self):
        from pyspark.sql import functions as F

        import parseo

        def cargar(fuente):
            ruta = (
                DATOS / f"fuente={fuente}" / f"anio={ATRASA.year:04d}"
                / f"mes={ATRASA.month:02d}" / f"dia={ATRASA.day:02d}" / "datos.json"
            )
            return json.loads(ruta.read_text(encoding="utf-8"))

        esperadas = parseo.unir(
            parseo.demanda(cargar("ree_demanda")),
            parseo.precio(cargar("ree_precio")),
            parseo.temperatura(cargar("clima_temperatura"), ATRASA),
        )
        obtenidas = sorted(
            (
                r.asDict()
                for r in self.filas.withColumn(
                    "marca", F.date_format("momento_utc", "yyyy-MM-dd HH:mm:ss")
                ).collect()
            ),
            key=lambda f: f["marca"],
        )

        self.assertEqual(len(obtenidas), len(esperadas))
        for got, exp in zip(obtenidas, esperadas):
            self.assertEqual(got["marca"], exp["momento_utc"].strftime("%Y-%m-%d %H:%M:%S"))
            self.assertAlmostEqual(got["temperatura_c"], exp["temperatura_c"], places=6)


def tearDownModule():
    if _SESION is not None:
        _SESION.stop()


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(SparkSession is None, "pyspark no instalado")
class ReglasDeCalidadCoincidenEnLosDosCaminos(unittest.TestCase):
    """Spark y la referencia en Python deben emitir el mismo veredicto.

    Aqui comparar las dos implementaciones SI es valido, al reves que con la
    conversion horaria: las reglas de calidad son una especificacion propia, no
    un hecho externo. `calidad.revisar` esta probado contra valores esperados
    en test_transformacion, y esto comprueba que el camino de Spark no se
    desvia de el. Las dos cuentan por medios distintos —agregados frente a
    recorrer listas— y redactan el veredicto con la misma funcion.
    """

    ESQUEMA = "momento_utc timestamp, demanda_mw double, precio_pvpc_eur_mwh double, precio_spot_eur_mwh double, temperatura_c double"

    @classmethod
    def setUpClass(cls):
        import calidad
        import transformacion

        cls.calidad = calidad
        cls.transformacion = transformacion

    def _dia(self, filas):
        from datetime import datetime, timezone

        base = datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc)
        return [
            {
                "momento_utc": base.replace(hour=h % 24),
                "demanda_mw": 25000.0,
                "precio_pvpc_eur_mwh": 80.0,
                "precio_spot_eur_mwh": 2.0,
                "temperatura_c": 7.0,
            }
            for h in range(filas)
        ]

    def _comparar(self, filas, nombre):
        from datetime import date

        dia = date(2024, 3, 1)
        esperado = self.calidad.revisar(filas, dia)

        df = sesion().createDataFrame(
            [tuple(f[c] for c in ("momento_utc", *self.calidad.COLUMNAS)) for f in filas],
            schema=self.ESQUEMA,
        )
        obtenido = self.transformacion.revisar(df, dia)

        self.assertEqual(sorted(obtenido["errores"]), sorted(esperado.errores), f"errores · {nombre}")
        self.assertEqual(sorted(obtenido["avisos"]), sorted(esperado.avisos), f"avisos · {nombre}")
        self.assertEqual(obtenido["filas"], esperado.filas, f"filas · {nombre}")

    def test_dia_completo(self):
        self._comparar(self._dia(24), "dia completo")

    def test_faltan_horas(self):
        self._comparar(self._dia(21), "faltan tres horas")

    def test_instante_duplicado(self):
        filas = self._dia(24)
        filas.append(dict(filas[5]))
        self._comparar(filas, "un instante duplicado")

    def test_demanda_completamente_vacia(self):
        filas = self._dia(24)
        for f in filas:
            f["demanda_mw"] = None
        self._comparar(filas, "demanda toda vacia")

    def test_demanda_fuera_de_rango(self):
        filas = self._dia(24)
        filas[3]["demanda_mw"] = 999.0
        filas[7]["demanda_mw"] = 99999.0
        self._comparar(filas, "demanda fuera de rango")

    def test_temperatura_fuera_de_rango(self):
        filas = self._dia(24)
        filas[2]["temperatura_c"] = -80.0
        self._comparar(filas, "temperatura fuera de rango")

    def test_nulos_en_columnas_que_no_son_la_demanda(self):
        filas = self._dia(24)
        for f in filas[:4]:
            f["temperatura_c"] = None
        filas[9]["precio_spot_eur_mwh"] = None
        self._comparar(filas, "nulos sueltos")

    def test_varios_problemas_a_la_vez(self):
        filas = self._dia(20)
        filas.append(dict(filas[0]))
        filas[1]["temperatura_c"] = None
        filas[2]["demanda_mw"] = 60000.0
        self._comparar(filas, "varios problemas")
