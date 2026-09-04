"""Los dos días al año que no tienen 24 horas, con datos reales.

El domingo de marzo dura 23 horas y el de octubre 25. Son los dos días en que
las tres fuentes pueden descuadrar sin que nada falle, y donde más fácil es
perder o duplicar una hora en silencio.

El 27 de octubre importa especialmente: la hora local 02:00 ocurre dos veces,
con desfases distintos. La ingesta anterior pedía la temperatura en
`Europe/Madrid` y la API devolvía 24 etiquetas a desfase fijo, así que una de
las dos horas simplemente no existía. Pidiéndola en UTC son 25 instantes
distintos y ninguno se pisa.

    python3 -m unittest tests.test_cambio_de_hora -v
"""

import json
import pathlib
import sys
import unittest
from datetime import date

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src" / "glue"))

import calidad  # noqa: E402
import parseo  # noqa: E402
import tiempo  # noqa: E402

DATOS = pathlib.Path(__file__).resolve().parent / "datos"

ADELANTA = date(2024, 3, 31)  # 23 horas
ATRASA = date(2024, 10, 27)  # 25 horas


def _cargar(fuente, dia):
    ruta = (
        DATOS / f"fuente={fuente}" / f"anio={dia.year:04d}"
        / f"mes={dia.month:02d}" / f"dia={dia.day:02d}" / "datos.json"
    )
    return json.loads(ruta.read_text(encoding="utf-8"))


def _filas(dia):
    return sorted(
        parseo.unir(
            parseo.demanda(_cargar("ree_demanda", dia)),
            parseo.precio(_cargar("ree_precio", dia)),
            parseo.temperatura(_cargar("clima_temperatura", dia), dia),
        ),
        key=lambda f: f["momento_utc"],
    )


@unittest.skipIf(not DATOS.exists(), "faltan los ficheros de ejemplo en tests/datos")
class DiaQueAdelanta(unittest.TestCase):
    """31 de marzo de 2024: a las 02:00 locales el reloj salta a las 03:00."""

    def setUp(self):
        self.filas = _filas(ADELANTA)

    def test_el_dia_tiene_23_filas(self):
        self.assertEqual(tiempo.horas_esperadas(ADELANTA), 23)
        self.assertEqual(len(self.filas), 23)

    def test_no_hay_errores_ni_avisos(self):
        informe = calidad.revisar(self.filas, ADELANTA)
        self.assertEqual(informe.errores, [])
        self.assertEqual(informe.avisos, [])

    def test_la_hora_que_no_existe_no_aparece(self):
        """Las 02:00 locales no llegan a ocurrir: se pasa de 01:00 a 03:00."""
        horas = [tiempo.utc_a_local(f["momento_utc"]).strftime("%H:%M") for f in self.filas]
        self.assertIn("01:00", horas)
        self.assertNotIn("02:00", horas)
        self.assertIn("03:00", horas)

    def test_ninguna_columna_queda_vacia(self):
        for fila in self.filas:
            for columna in ("demanda_mw", "precio_pvpc_eur_mwh", "temperatura_c"):
                self.assertIsNotNone(fila[columna], f"{fila['momento_utc']} {columna}")


@unittest.skipIf(not DATOS.exists(), "faltan los ficheros de ejemplo en tests/datos")
class DiaQueAtrasa(unittest.TestCase):
    """27 de octubre de 2024: las 02:00 locales ocurren dos veces."""

    def setUp(self):
        self.filas = _filas(ATRASA)

    def test_el_dia_tiene_25_filas(self):
        self.assertEqual(tiempo.horas_esperadas(ATRASA), 25)
        self.assertEqual(len(self.filas), 25)

    def test_no_hay_errores_ni_avisos(self):
        informe = calidad.revisar(self.filas, ATRASA)
        self.assertEqual(informe.errores, [])
        self.assertEqual(informe.avisos, [])

    def test_la_hora_repetida_aparece_dos_veces_con_desfases_distintos(self):
        """La prueba que la ingesta anterior no podía pasar.

        Pidiendo la temperatura en hora local, la API devolvía 24 etiquetas a
        desfase fijo y una de las dos 02:00 se perdía. En UTC son dos instantes
        separados por una hora y ambos sobreviven.
        """
        dos = [f for f in self.filas if tiempo.utc_a_local(f["momento_utc"]).hour == 2]
        self.assertEqual(len(dos), 2)

        desfases = {tiempo.utc_a_local(f["momento_utc"]).utcoffset() for f in dos}
        self.assertEqual(len(desfases), 2, "las dos 02:00 deben tener desfases distintos")

        separacion = dos[1]["momento_utc"] - dos[0]["momento_utc"]
        self.assertEqual(separacion.total_seconds(), 3600)

        self.assertNotEqual(dos[0]["temperatura_c"], dos[1]["temperatura_c"])

    def test_los_instantes_no_se_repiten(self):
        instantes = [f["momento_utc"] for f in self.filas]
        self.assertEqual(len(instantes), len(set(instantes)))

    def test_ninguna_columna_queda_vacia(self):
        for fila in self.filas:
            for columna in ("demanda_mw", "precio_pvpc_eur_mwh", "temperatura_c"):
                self.assertIsNotNone(fila[columna], f"{fila['momento_utc']} {columna}")


if __name__ == "__main__":
    unittest.main()
