"""Normalización de tiempo entre las dos fuentes.

Ninguna función de este módulo depende de Spark: se ejecutan y se prueban
sin levantar una sesión.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")


def ventana_utc(dia: date):
    """(inicio, fin) en UTC del día local de Madrid.

    El proyecto piensa en días locales —es lo que particiona la tabla y lo que
    entiende quien mira el consumo— pero cruza las fuentes por instante UTC.
    Esta función es la única traducción entre las dos ideas.

    Intervalo semiabierto: `fin` ya pertenece al día siguiente.
    """
    inicio = datetime.combine(dia, datetime.min.time(), tzinfo=MADRID)
    fin = datetime.combine(dia + timedelta(days=1), datetime.min.time(), tzinfo=MADRID)
    return inicio.astimezone(UTC), fin.astimezone(UTC)


def horas_esperadas(dia: date) -> int:
    """Horas reales que tiene un día en Madrid.

    23 el domingo que adelanta, 25 el que atrasa, 24 el resto. Validar contra
    24 fijo marca como incompletos dos días al año que están completos.
    """
    inicio, fin = ventana_utc(dia)
    return round((fin - inicio).total_seconds() / 3600)


def hay_cambio_de_hora(dia: date) -> bool:
    return horas_esperadas(dia) != 24


def marca_utc(marca: str) -> datetime:
    """Marca sin desfase de una fuente pedida en UTC -> instante UTC.

    A Open-Meteo se le pide `timezone=UTC`, así que `2024-03-01T00:00` ya es un
    instante y no hay ningún huso que deducir.

    Se pedía en hora local hasta que se comprobó que la API construye la serie
    con el desfase vigente el día de la petición, no el del día de los datos:
    consultado en septiembre, un día de enero llega etiquetado en UTC+2.
    Reinterpretar esas etiquetas como hora de Madrid corría todo el invierno
    una hora sin que fallara nada. Pedir en UTC quita el problema en origen.
    """
    ingenua = datetime.fromisoformat(marca)
    if ingenua.tzinfo is not None:
        raise ValueError(f"se esperaba una marca sin desfase: {marca!r}")
    return ingenua.replace(tzinfo=UTC)


def desfasada_a_utc(marca: str) -> datetime:
    """Marca con desfase explícito -> instante UTC. REE ya lo trae correcto."""
    con_desfase = datetime.fromisoformat(marca)
    if con_desfase.tzinfo is None:
        raise ValueError(f"se esperaba una marca con desfase: {marca!r}")
    return con_desfase.astimezone(UTC)


def utc_a_local(instante: datetime) -> datetime:
    return instante.astimezone(MADRID)
