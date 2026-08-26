import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

import boto3

BUCKET_RAW = os.environ["BUCKET_RAW"]
INTENTOS = int(os.environ.get("INTENTOS", "6"))
ESPERA_BASE = float(os.environ.get("ESPERA_BASE", "1.5"))
TIMEOUT = int(os.environ.get("TIMEOUT_HTTP", "25"))

s3 = boto3.client("s3")


def log(evento, **campos):
    print(json.dumps({"evento": evento, **campos}, ensure_ascii=False), file=sys.stdout)


class SinRespuesta(Exception):
    pass


def pedir_json(url, params, etiqueta):
    """GET con reintentos y espera exponencial.

    Reintenta también ante 400, que en otro contexto sería un error definitivo:
    apidatos.ree.es devuelve 400 "Error Interno" de forma intermitente para
    peticiones correctas, y a la siguiente responde 200 con los mismos
    parámetros. Sin este reintento la ingesta es una lotería.
    """
    completa = f"{url}?{urllib.parse.urlencode(params)}"
    ultimo = None

    for intento in range(1, INTENTOS + 1):
        try:
            peticion = urllib.request.Request(
                completa, headers={"Accept": "application/json", "User-Agent": "caudalit-pipeline"}
            )
            with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
                cuerpo = respuesta.read().decode("utf-8")
                log("http_ok", fuente=etiqueta, intento=intento, bytes=len(cuerpo))
                return json.loads(cuerpo)

        except urllib.error.HTTPError as e:
            ultimo = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            ultimo = f"red: {e.reason}"
        except json.JSONDecodeError:
            ultimo = "respuesta no es JSON valido"

        if intento < INTENTOS:
            # Jitter: sin él, varias ejecuciones que fallan a la vez reintentan
            # sincronizadas y golpean el origen en el mismo instante.
            espera = ESPERA_BASE * (2 ** (intento - 1)) + random.uniform(0, 1)
            log("http_reintento", fuente=etiqueta, intento=intento, motivo=ultimo, espera_s=round(espera, 2))
            time.sleep(espera)

    log("http_agotado", fuente=etiqueta, intentos=INTENTOS, motivo=ultimo)
    raise SinRespuesta(f"{etiqueta}: sin respuesta tras {INTENTOS} intentos ({ultimo})")


def fecha_objetivo(event):
    """El día anterior por defecto: el actual todavía está incompleto."""
    if event and event.get("fecha"):
        return date.fromisoformat(event["fecha"])
    return date.today() - timedelta(days=1)


def guardar(fuente, dia, payload):
    """Escribe el JSON tal cual llegó, particionado por la fecha del dato.

    La clave es determinista: reprocesar un día sobrescribe su archivo en vez
    de duplicarlo.
    """
    clave = (
        f"fuente={fuente}"
        f"/anio={dia.year:04d}/mes={dia.month:02d}/dia={dia.day:02d}"
        f"/datos.json"
    )
    cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    s3.put_object(
        Bucket=BUCKET_RAW,
        Key=clave,
        Body=cuerpo,
        ContentType="application/json",
    )
    log("s3_escrito", fuente=fuente, clave=clave, bytes=len(cuerpo))
    return clave
