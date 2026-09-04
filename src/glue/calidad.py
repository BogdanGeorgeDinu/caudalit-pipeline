"""Reglas de calidad sobre las filas ya cruzadas.

Separadas del cruce a propósito: una regla que cambia no debería obligar a
tocar la transformación.
"""

from dataclasses import dataclass, field
from datetime import date

from tiempo import horas_esperadas

# Rangos plausibles, no límites físicos. Sirven para detectar unidades
# cambiadas o valores centinela, no para juzgar la red eléctrica.
DEMANDA_MIN_MW = 10_000.0
DEMANDA_MAX_MW = 50_000.0
TEMPERATURA_MIN_C = -25.0
TEMPERATURA_MAX_C = 50.0

COLUMNAS = ("demanda_mw", "precio_pvpc_eur_mwh", "precio_spot_eur_mwh", "temperatura_c")

# Columnas con rango de plausibilidad, y su rango.
RANGOS = {
    "demanda_mw": (DEMANDA_MIN_MW, DEMANDA_MAX_MW),
    "temperatura_c": (TEMPERATURA_MIN_C, TEMPERATURA_MAX_C),
}


def veredicto(filas, esperadas, instantes_distintos, nulos, fuera_de_rango):
    """Las reglas, en un solo sitio, a partir de numeros ya contados.

    La transformacion en Spark cuenta con agregados y la referencia en Python
    recorriendo listas, pero el juicio se emite aqui. Tener las reglas dos
    veces era como se colo el desfase horario de esta fase: dos
    implementaciones que coinciden entre si no demuestran nada.
    """
    errores, avisos = [], []

    if not filas:
        return ["sin filas"], []

    duplicados = filas - instantes_distintos
    if duplicados:
        errores.append(f"{duplicados} instantes duplicados")

    if nulos.get("demanda_mw", 0) == filas:
        errores.append("demanda_mw completamente vacia")

    for columna in RANGOS:
        fuera = fuera_de_rango.get(columna, 0)
        if fuera:
            errores.append(f"{columna}: {fuera} valores fuera de rango")

    if filas != esperadas:
        avisos.append(f"{filas} filas frente a {esperadas} esperadas")

    for columna, vacios in nulos.items():
        if columna != "demanda_mw" and vacios:
            avisos.append(f"{columna}: {vacios} nulos")

    return errores, avisos


@dataclass
class Informe:
    dia: date
    filas: int
    filas_esperadas: int
    nulos: dict = field(default_factory=dict)
    errores: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return not self.errores

    def como_dict(self):
        return {
            "dia": self.dia.isoformat(),
            "filas": self.filas,
            "filas_esperadas": self.filas_esperadas,
            "nulos": self.nulos,
            "errores": self.errores,
            "avisos": self.avisos,
            "valido": self.valido,
        }


def revisar(filas, dia: date) -> Informe:
    esperadas = horas_esperadas(dia)
    informe = Informe(dia=dia, filas=len(filas), filas_esperadas=esperadas)

    informe.nulos = {c: sum(1 for f in filas if f.get(c) is None) for c in COLUMNAS}
    fuera = {
        c: sum(
            1
            for f in filas
            if f.get(c) is not None and not minimo <= f[c] <= maximo
        )
        for c, (minimo, maximo) in RANGOS.items()
    }
    instantes = len({f["momento_utc"] for f in filas})

    informe.errores, informe.avisos = veredicto(
        len(filas), esperadas, instantes, informe.nulos, fuera
    )
    return informe
