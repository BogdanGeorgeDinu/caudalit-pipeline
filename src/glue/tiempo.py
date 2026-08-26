"""Normalización de tiempo entre las dos fuentes.

Ninguna función de este módulo depende de Spark: se ejecutan y se prueban
sin levantar una sesión.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")


def horas_esperadas(dia: date) -> int:
    """Horas reales que tiene un día en Madrid.

    23 el domingo que adelanta, 25 el que atrasa, 24 el resto. Validar contra
    24 fijo marca como incompletos dos días al año que están completos.
    """
    inicio = datetime.combine(dia, datetime.min.time(), tzinfo=MADRID)
    fin = datetime.combine(dia + timedelta(days=1), datetime.min.time(), tzinfo=MADRID)
    return round((fin.astimezone(UTC) - inicio.astimezone(UTC)).total_seconds() / 3600)


def hay_cambio_de_hora(dia: date) -> bool:
    return horas_esperadas(dia) != 24


def local_a_utc(marca: str) -> datetime:
    """Hora local de Madrid sin desfase -> instante UTC.

    Open-Meteo entrega `2024-03-01T00:00` y, en otro campo, un
    `utc_offset_seconds` que corresponde al día en que se hace la petición, no
    al día de los datos. Usar ese campo desplaza una hora todo el invierno.
    """
    ingenua = datetime.fromisoformat(marca)
    if ingenua.tzinfo is not None:
        raise ValueError(f"se esperaba una marca sin desfase: {marca!r}")
    return ingenua.replace(tzinfo=MADRID).astimezone(UTC)


def desfasada_a_utc(marca: str) -> datetime:
    """Marca con desfase explícito -> instante UTC. REE ya lo trae correcto."""
    con_desfase = datetime.fromisoformat(marca)
    if con_desfase.tzinfo is None:
        raise ValueError(f"se esperaba una marca con desfase: {marca!r}")
    return con_desfase.astimezone(UTC)


def utc_a_local(instante: datetime) -> datetime:
    return instante.astimezone(MADRID)


def calendario(dia: date):
    """[(hora local sin desfase, instante UTC)] para todas las horas del día.

    El job lo difunde como tabla y cruza por la cadena local, en vez de llamar
    a `to_utc_timestamp`. Las reglas horarias quedan así en un sitio probado y
    el resultado no depende de la versión de Spark ni de su configuración.

    El domingo que atrasa, la hora local se repite: se conserva la primera
    aparición, que es la que el parseo también conserva.
    """
    instante = datetime.combine(dia, datetime.min.time(), tzinfo=MADRID).astimezone(UTC)
    fin = datetime.combine(dia + timedelta(days=1), datetime.min.time(), tzinfo=MADRID).astimezone(UTC)

    vistas = {}
    while instante < fin:
        local = instante.astimezone(MADRID).strftime("%Y-%m-%dT%H:%M")
        vistas.setdefault(local, instante)
        instante += timedelta(hours=1)

    return sorted(vistas.items(), key=lambda par: par[1])
