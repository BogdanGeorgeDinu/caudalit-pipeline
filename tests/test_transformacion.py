"""Pruebas de la lógica de transformación. Sin Spark: se ejecutan en segundos.

    python3 -m unittest discover -s tests -v
"""

import pathlib
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "glue"))

import calidad  # noqa: E402
import parseo  # noqa: E402
import tiempo  # noqa: E402


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Tiempo(unittest.TestCase):
    def test_dia_normal_tiene_24_horas(self):
        self.assertEqual(tiempo.horas_esperadas(date(2024, 3, 1)), 24)

    def test_domingo_que_adelanta_tiene_23(self):
        self.assertEqual(tiempo.horas_esperadas(date(2024, 3, 31)), 23)

    def test_domingo_que_atrasa_tiene_25(self):
        self.assertEqual(tiempo.horas_esperadas(date(2024, 10, 27)), 25)

    def test_el_dia_local_de_invierno_empieza_a_las_23_utc(self):
        self.assertEqual(
            tiempo.ventana_utc(date(2024, 3, 1)),
            (utc(2024, 2, 29, 23, 0), utc(2024, 3, 1, 23, 0)),
        )

    def test_el_dia_local_de_verano_empieza_a_las_22_utc(self):
        self.assertEqual(
            tiempo.ventana_utc(date(2024, 7, 15)),
            (utc(2024, 7, 14, 22, 0), utc(2024, 7, 15, 22, 0)),
        )

    def test_la_marca_de_open_meteo_ya_es_utc(self):
        """Se pide con `timezone=UTC`: no hay huso que deducir.

        La primera versión pedía en Europe/Madrid y reinterpretaba la etiqueta
        como hora local. La API construye la serie con el desfase vigente el
        día de la petición, así que en invierno eso corría el dato una hora.
        """
        self.assertEqual(tiempo.marca_utc("2024-03-01T00:00"), utc(2024, 3, 1, 0, 0))

    def test_las_dos_fuentes_convergen_en_el_mismo_instante(self):
        """La medianoche local del 1 de marzo, vista por las dos fuentes."""
        self.assertEqual(
            tiempo.marca_utc("2024-02-29T23:00"),
            tiempo.desfasada_a_utc("2024-03-01T00:00:00.000+01:00"),
        )

    def test_rechaza_marca_con_desfase_donde_no_toca(self):
        with self.assertRaises(ValueError):
            tiempo.marca_utc("2024-03-01T00:00:00+01:00")

    def test_rechaza_marca_sin_desfase_donde_hace_falta(self):
        with self.assertRaises(ValueError):
            tiempo.desfasada_a_utc("2024-03-01T00:00")


class Parseo(unittest.TestCase):
    def test_demanda_se_aplana_a_filas_horarias(self):
        payload = {
            "included": [
                {
                    "attributes": {
                        "title": "Demanda",
                        "values": [
                            {"value": 26056.6, "datetime": "2024-03-01T00:00:00.000+01:00"},
                            {"value": 24570.4, "datetime": "2024-03-01T01:00:00.000+01:00"},
                        ],
                    }
                }
            ]
        }
        filas = parseo.demanda(payload)
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["momento_utc"], utc(2024, 2, 29, 23, 0))
        self.assertEqual(filas[0]["demanda_mw"], 26056.6)

    def test_las_dos_series_de_precio_se_cruzan_por_instante(self):
        payload = {
            "included": [
                {
                    "attributes": {
                        "title": "PVPC",
                        "values": [{"value": 51.08, "datetime": "2024-03-01T00:00:00.000+01:00"}],
                    }
                },
                {
                    "attributes": {
                        "title": "Precio mercado spot",
                        "values": [{"value": 2.17, "datetime": "2024-03-01T00:00:00.000+01:00"}],
                    }
                },
            ]
        }
        filas = parseo.precio(payload)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["precio_pvpc_eur_mwh"], 51.08)
        self.assertEqual(filas[0]["precio_spot_eur_mwh"], 2.17)

    def test_una_serie_de_precio_ausente_deja_nulo_y_no_rompe(self):
        payload = {
            "included": [
                {
                    "attributes": {
                        "title": "PVPC",
                        "values": [{"value": 51.08, "datetime": "2024-03-01T00:00:00.000+01:00"}],
                    }
                }
            ]
        }
        filas = parseo.precio(payload)
        self.assertIsNone(filas[0]["precio_spot_eur_mwh"])

    def test_temperatura_toma_la_marca_como_instante_utc(self):
        payload = {
            "utc_offset_seconds": 0,
            "hourly": {"time": ["2024-02-29T23:00"], "temperature_2m": [5.8]},
        }
        filas = parseo.temperatura(payload, date(2024, 3, 1))
        self.assertEqual(filas[0]["momento_utc"], utc(2024, 2, 29, 23, 0))

    def test_temperatura_rechaza_un_payload_en_hora_local(self):
        """El fallo en alto que le faltaba a la primera versión de la fase.

        Con `utc_offset_seconds` distinto de cero las marcas no son instantes,
        y darlas por buenas desplaza el dato una hora sin romper nada.
        """
        payload = {
            "utc_offset_seconds": 7200,
            "hourly": {"time": ["2024-03-01T00:00"], "temperature_2m": [5.8]},
        }
        with self.assertRaises(ValueError):
            parseo.temperatura(payload, date(2024, 3, 1))

    def test_temperatura_recorta_a_la_ventana_del_dia_local(self):
        """El payload trae dos días UTC; sólo entra el día local de Madrid."""
        payload = {
            "utc_offset_seconds": 0,
            "hourly": {
                "time": ["2024-02-29T22:00", "2024-02-29T23:00", "2024-03-01T23:00"],
                "temperature_2m": [4.0, 5.8, 6.3],
            },
        }
        filas = parseo.temperatura(payload, date(2024, 3, 1))
        self.assertEqual([f["momento_utc"] for f in filas], [utc(2024, 2, 29, 23, 0)])

    def test_temperatura_rechaza_arrays_descuadrados(self):
        payload = {
            "utc_offset_seconds": 0,
            "hourly": {"time": ["2024-03-01T00:00", "2024-03-01T01:00"], "temperature_2m": [5.8]},
        }
        with self.assertRaises(ValueError):
            parseo.temperatura(payload, date(2024, 3, 1))

    def test_unir_conserva_las_horas_aunque_falte_una_fuente(self):
        filas = parseo.unir(
            [{"momento_utc": utc(2024, 3, 1, 0, 0), "demanda_mw": 100.0}],
            [],
            [{"momento_utc": utc(2024, 3, 1, 1, 0), "temperatura_c": 5.0}],
        )
        self.assertEqual(len(filas), 2)
        self.assertIsNone(filas[0]["temperatura_c"])
        self.assertIsNone(filas[1]["demanda_mw"])

    def test_dia_de_clave(self):
        clave = "fuente=ree_demanda/anio=2024/mes=03/dia=01/datos.json"
        self.assertEqual(parseo.dia_de_clave(clave), date(2024, 3, 1))


class Calidad(unittest.TestCase):
    def _fila(self, hora, **extra):
        base = {
            "momento_utc": utc(2024, 3, 1, hora, 0),
            "demanda_mw": 25000.0,
            "precio_pvpc_eur_mwh": 50.0,
            "precio_spot_eur_mwh": 2.0,
            "temperatura_c": 10.0,
        }
        base.update(extra)
        return base

    def test_dia_completo_es_valido(self):
        informe = calidad.revisar([self._fila(h) for h in range(24)], date(2024, 3, 1))
        self.assertTrue(informe.valido)
        self.assertEqual(informe.avisos, [])

    def test_dia_sin_filas_es_error(self):
        self.assertFalse(calidad.revisar([], date(2024, 3, 1)).valido)

    def test_faltan_horas_es_aviso_no_error(self):
        informe = calidad.revisar([self._fila(h) for h in range(20)], date(2024, 3, 1))
        self.assertTrue(informe.valido)
        self.assertTrue(informe.avisos)

    def test_23_filas_el_dia_que_adelanta_no_genera_aviso(self):
        filas = [
            {**self._fila(h), "momento_utc": utc(2024, 3, 31, h, 0)} for h in range(23)
        ]
        informe = calidad.revisar(filas, date(2024, 3, 31))
        self.assertEqual(informe.avisos, [])

    def test_instantes_duplicados_son_error(self):
        informe = calidad.revisar([self._fila(0), self._fila(0)], date(2024, 3, 1))
        self.assertFalse(informe.valido)

    def test_demanda_fuera_de_rango_es_error(self):
        informe = calidad.revisar([self._fila(0, demanda_mw=1_000_000.0)], date(2024, 3, 1))
        self.assertFalse(informe.valido)

    def test_demanda_toda_vacia_es_error(self):
        informe = calidad.revisar([self._fila(h, demanda_mw=None) for h in range(24)], date(2024, 3, 1))
        self.assertFalse(informe.valido)

    def test_temperatura_vacia_no_invalida_el_dia_pero_avisa(self):
        """La demanda responde la pregunta de negocio; la temperatura no.

        Un dia sin temperatura queda cojo, no inutil: se escribe y se anota.
        Antes solo se contaban los nulos y el aviso no llegaba a emitirse,
        aunque la documentacion de la fase decia que si.
        """
        informe = calidad.revisar([self._fila(h, temperatura_c=None) for h in range(24)], date(2024, 3, 1))
        self.assertTrue(informe.valido)
        self.assertEqual(informe.nulos["temperatura_c"], 24)
        self.assertIn("temperatura_c: 24 nulos", informe.avisos)

    def test_un_hueco_suelto_de_precio_es_aviso(self):
        filas = [self._fila(h) for h in range(24)]
        filas[7]["precio_spot_eur_mwh"] = None
        informe = calidad.revisar(filas, date(2024, 3, 1))
        self.assertTrue(informe.valido)
        self.assertEqual(informe.avisos, ["precio_spot_eur_mwh: 1 nulos"])

    def test_la_demanda_incompleta_no_es_error_si_no_esta_toda_vacia(self):
        """Solo la demanda completamente vacia tumba el dia."""
        filas = [self._fila(h) for h in range(24)]
        filas[3]["demanda_mw"] = None
        informe = calidad.revisar(filas, date(2024, 3, 1))
        self.assertTrue(informe.valido)
        self.assertEqual(informe.avisos, [])


if __name__ == "__main__":
    unittest.main()
