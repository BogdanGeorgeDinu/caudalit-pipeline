"""Pruebas de las Lambdas de ingesta, sin red y sin AWS.

La ingesta no tenia ninguna prueba: toda la suite miraba la transformacion.
Es justo la parte que habla con una API que se sabe que falla sola, asi que
la logica de reintentos merece estar cubierta.

`boto3` no esta instalado ni hace falta: se sustituye por un doble antes de
importar el modulo, igual que `urllib.request.urlopen` y `time.sleep`.

    python3 -m unittest tests.test_ingesta -v
"""

import io
import json
import pathlib
import sys
import types
import unittest
import urllib.error
from datetime import date, timedelta
from unittest import mock

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src" / "lambdas"))


class _S3Falso:
    def __init__(self):
        self.puestos = []

    def put_object(self, **kwargs):
        self.puestos.append(kwargs)
        return {}


_s3 = _S3Falso()
_boto3 = types.ModuleType("boto3")
_boto3.client = lambda *a, **k: _s3
sys.modules.setdefault("boto3", _boto3)

import os  # noqa: E402

os.environ.setdefault("BUCKET_RAW", "bucket-de-prueba")

import comun  # noqa: E402


def _respuesta(payload):
    cuerpo = json.dumps(payload).encode("utf-8")
    doble = mock.MagicMock()
    doble.__enter__.return_value.read.return_value = cuerpo
    doble.__exit__.return_value = False
    return doble


def _error(codigo):
    return urllib.error.HTTPError("http://x", codigo, "Error Interno", {}, io.BytesIO(b""))


class Reintentos(unittest.TestCase):
    """La decision que define la Fase 4: reintentar tambien ante un 400."""

    def setUp(self):
        self.esperas = []
        self.eventos = []

    def _pedir(self, efectos):
        """Ejecuta pedir_json sin red, sin esperas reales y sin ruido en la salida."""
        registrar = lambda evento, **campos: self.eventos.append({"evento": evento, **campos})
        with mock.patch.object(comun.urllib.request, "urlopen", side_effect=efectos), \
             mock.patch.object(comun.time, "sleep", self.esperas.append), \
             mock.patch.object(comun, "log", registrar):
            return comun.pedir_json("http://x", {"a": 1}, "prueba")

    def test_a_la_primera_no_espera(self):
        self.assertEqual(self._pedir([_respuesta({"ok": True})]), {"ok": True})
        self.assertEqual(self.esperas, [])

    def test_reintenta_ante_400_y_acaba_devolviendo_el_json(self):
        """apidatos.ree.es devuelve 400 para peticiones correctas y luego 200."""
        efectos = [_error(400), _error(400), _respuesta({"ok": True})]
        self.assertEqual(self._pedir(efectos), {"ok": True})
        self.assertEqual(len(self.esperas), 2)

    def test_la_espera_crece_de_forma_exponencial(self):
        efectos = [_error(400)] * 3 + [_respuesta({})]
        self._pedir(efectos)
        # 1,5 · 3 · 6 mas un jitter de hasta 1 s en cada una.
        for i, espera in enumerate(self.esperas):
            base = comun.ESPERA_BASE * 2**i
            self.assertGreaterEqual(espera, base)
            self.assertLess(espera, base + 1)

    def test_el_jitter_desincroniza_dos_ejecuciones(self):
        """Sin jitter, varias ejecuciones que fallan a la vez golpean juntas."""
        primera, segunda = [], []
        for destino in (primera, segunda):
            self.esperas = destino
            self._pedir([_error(400)] * 3 + [_respuesta({})])
        self.assertNotEqual(primera, segunda)

    def test_agota_los_intentos_y_falla_en_alto(self):
        efectos = [_error(400)] * comun.INTENTOS
        with self.assertRaises(comun.SinRespuesta):
            self._pedir(efectos)
        self.assertEqual(len(self.esperas), comun.INTENTOS - 1)

    def test_un_json_invalido_tambien_se_reintenta(self):
        malo = mock.MagicMock()
        malo.__enter__.return_value.read.return_value = b"<html>vaya</html>"
        malo.__exit__.return_value = False
        self.assertEqual(self._pedir([malo, _respuesta({"ok": True})]), {"ok": True})
        self.assertEqual(len(self.esperas), 1)


    def test_deja_rastro_en_el_log_para_poder_medir_los_fallos(self):
        """Los logs en JSON existen para filtrar por http_reintento en
        CloudWatch y medir cuantas veces falla REE de verdad, no suponerlo."""
        self._pedir([_error(400), _error(400), _respuesta({})])

        tipos = [e["evento"] for e in self.eventos]
        self.assertEqual(tipos, ["http_reintento", "http_reintento", "http_ok"])

        primero = self.eventos[0]
        self.assertEqual(primero["fuente"], "prueba")
        self.assertEqual(primero["intento"], 1)
        self.assertEqual(primero["motivo"], "HTTP 400")
        self.assertIn("espera_s", primero)

    def test_al_agotarse_lo_dice_con_el_motivo_del_ultimo_fallo(self):
        with self.assertRaises(comun.SinRespuesta):
            self._pedir([_error(400)] * (comun.INTENTOS - 1) + [_error(503)])
        ultimo = self.eventos[-1]
        self.assertEqual(ultimo["evento"], "http_agotado")
        self.assertEqual(ultimo["motivo"], "HTTP 503")


class FechaObjetivo(unittest.TestCase):
    def test_por_defecto_el_dia_anterior(self):
        self.assertEqual(comun.fecha_objetivo(None), date.today() - timedelta(days=1))
        self.assertEqual(comun.fecha_objetivo({}), date.today() - timedelta(days=1))

    def test_respeta_la_fecha_del_evento(self):
        self.assertEqual(comun.fecha_objetivo({"fecha": "2024-03-01"}), date(2024, 3, 1))


class ClaveEnS3(unittest.TestCase):
    def setUp(self):
        self._log = mock.patch.object(comun, "log", lambda *a, **k: None)
        self._log.start()
        self.addCleanup(self._log.stop)

    def test_la_clave_no_depende_del_momento_de_ejecucion(self):
        """La ingesta es idempotente: reprocesar sobrescribe, no duplica."""
        _s3.puestos.clear()
        una = comun.guardar("ree_demanda", date(2024, 3, 1), {"a": 1})
        otra = comun.guardar("ree_demanda", date(2024, 3, 1), {"a": 2})
        self.assertEqual(una, otra)
        self.assertEqual(una, "fuente=ree_demanda/anio=2024/mes=03/dia=01/datos.json")

    def test_los_meses_y_dias_van_con_cero_delante(self):
        """Athena deduce las particiones del patron: espera mes=03, no mes=3."""
        clave = comun.guardar("clima_temperatura", date(2024, 3, 5), {})
        self.assertIn("/mes=03/dia=05/", clave)


class LambdaDeREE(unittest.TestCase):
    def test_guarda_la_demanda_antes_de_pedir_el_precio(self):
        """Regresion: si la segunda peticion agota los reintentos y la Lambda
        se queda sin tiempo, la primera ya tiene que estar en S3."""
        import ree

        self.addCleanup(mock.patch.object(ree, "log", lambda *a, **k: None).stop)
        mock.patch.object(ree, "log", lambda *a, **k: None).start()
        orden = []

        def pedir(url, params, etiqueta):
            orden.append(f"pide:{etiqueta}")
            return {"fuente": etiqueta}

        def guardar(fuente, dia, payload):
            orden.append(f"guarda:{fuente}")
            return f"clave/{fuente}"

        with mock.patch.object(ree, "pedir_json", pedir), \
             mock.patch.object(ree, "guardar", guardar):
            ree.handler({"fecha": "2024-03-01"}, None)

        self.assertEqual(
            orden,
            ["pide:ree_demanda", "guarda:ree_demanda", "pide:ree_precio", "guarda:ree_precio"],
        )


class LambdaDeClima(unittest.TestCase):
    def test_pide_en_utc_y_cubre_tambien_la_vispera(self):
        """El dia local de Madrid empieza a las 22:00 o 23:00 UTC del dia anterior."""
        import openmeteo

        self.addCleanup(mock.patch.object(openmeteo, "log", lambda *a, **k: None).stop)
        mock.patch.object(openmeteo, "log", lambda *a, **k: None).start()
        capturado = {}

        def pedir(url, params, etiqueta):
            capturado.update(params)
            return {}

        with mock.patch.object(openmeteo, "pedir_json", pedir), \
             mock.patch.object(openmeteo, "guardar", lambda *a: "clave"):
            openmeteo.handler({"fecha": "2024-03-01"}, None)

        self.assertEqual(capturado["timezone"], "UTC")
        self.assertEqual(capturado["start_date"], "2024-02-29")
        self.assertEqual(capturado["end_date"], "2024-03-01")


if __name__ == "__main__":
    unittest.main()
