"""Aplanado de los tres JSON crudos a filas horarias.

Python puro, sin Spark: es la especificación ejecutable de las reglas, y lo
que prueban los tests. El job de Glue aplica las mismas reglas con primitivas
de DataFrame.
"""

from datetime import date

from tiempo import desfasada_a_utc, local_a_utc

SERIE_PVPC = "PVPC"
SERIE_SPOT = "Precio mercado spot"


def _serie(payload, titulo):
    for bloque in payload.get("included", []):
        if bloque.get("attributes", {}).get("title") == titulo:
            return bloque["attributes"].get("values", [])
    return []


def demanda(payload):
    """[{momento_utc, demanda_mw}] a partir del JSON de demanda de REE."""
    valores = _serie(payload, "Demanda")
    return [
        {"momento_utc": desfasada_a_utc(v["datetime"]), "demanda_mw": _numero(v.get("value"))}
        for v in valores
        if v.get("datetime")
    ]


def precio(payload):
    """[{momento_utc, precio_pvpc_eur_mwh, precio_spot_eur_mwh}].

    Las dos series vienen en el mismo documento y se cruzan por instante: no
    se puede asumir que lleguen alineadas ni completas.
    """
    por_instante = {}
    for titulo, columna in ((SERIE_PVPC, "precio_pvpc_eur_mwh"), (SERIE_SPOT, "precio_spot_eur_mwh")):
        for v in _serie(payload, titulo):
            if not v.get("datetime"):
                continue
            fila = por_instante.setdefault(desfasada_a_utc(v["datetime"]), {})
            fila[columna] = _numero(v.get("value"))

    return [
        {
            "momento_utc": instante,
            "precio_pvpc_eur_mwh": fila.get("precio_pvpc_eur_mwh"),
            "precio_spot_eur_mwh": fila.get("precio_spot_eur_mwh"),
        }
        for instante, fila in sorted(por_instante.items())
    ]


def temperatura(payload):
    """[{momento_utc, temperatura_c}] a partir del JSON de Open-Meteo.

    Se ignora `utc_offset_seconds` a propósito: ver tiempo.local_a_utc.
    """
    horario = payload.get("hourly", {})
    marcas = horario.get("time", [])
    grados = horario.get("temperature_2m", [])

    if len(marcas) != len(grados):
        raise ValueError(f"time y temperature_2m no cuadran: {len(marcas)} vs {len(grados)}")

    filas = {}
    for marca, grado in zip(marcas, grados):
        # El domingo que atrasa, la hora local se repite y las dos entradas
        # caen en el mismo instante UTC. Sin desambiguador en el payload, se
        # conserva la primera y la validación lo cuenta como hueco.
        filas.setdefault(local_a_utc(marca), _numero(grado))

    return [{"momento_utc": k, "temperatura_c": v} for k, v in sorted(filas.items())]


def unir(demanda_filas, precio_filas, temperatura_filas):
    """Cruce por instante conservando huecos: un `outer` manual.

    Se conservan todos los instantes de las tres fuentes. Perder una hora en
    silencio porque una fuente no la trajo es peor que verla con un nulo.
    """
    combinadas = {}
    for grupo in (demanda_filas, precio_filas, temperatura_filas):
        for fila in grupo:
            combinadas.setdefault(fila["momento_utc"], {}).update(fila)

    columnas = ("demanda_mw", "precio_pvpc_eur_mwh", "precio_spot_eur_mwh", "temperatura_c")
    return [
        {"momento_utc": instante, **{c: fila.get(c) for c in columnas}}
        for instante, fila in sorted(combinadas.items())
    ]


def _numero(valor):
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def dia_de_clave(clave: str) -> date:
    """`fuente=x/anio=2024/mes=03/dia=01/datos.json` -> date(2024, 3, 1)."""
    partes = dict(p.split("=", 1) for p in clave.split("/") if "=" in p)
    return date(int(partes["anio"]), int(partes["mes"]), int(partes["dia"]))
