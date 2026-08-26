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

    if not filas:
        informe.errores.append("sin filas")
        return informe

    instantes = [f["momento_utc"] for f in filas]
    duplicados = len(instantes) - len(set(instantes))
    if duplicados:
        informe.errores.append(f"{duplicados} instantes duplicados")

    if len(filas) != esperadas:
        informe.avisos.append(f"{len(filas)} filas frente a {esperadas} esperadas")

    for columna in COLUMNAS:
        vacios = sum(1 for f in filas if f.get(columna) is None)
        informe.nulos[columna] = vacios

    # La demanda es la columna que responde la pregunta de negocio: sin ella
    # el día no sirve, y es un error, no un aviso.
    if informe.nulos["demanda_mw"] == len(filas):
        informe.errores.append("demanda_mw completamente vacia")

    _rango(informe, filas, "demanda_mw", DEMANDA_MIN_MW, DEMANDA_MAX_MW)
    _rango(informe, filas, "temperatura_c", TEMPERATURA_MIN_C, TEMPERATURA_MAX_C)

    return informe


def _rango(informe, filas, columna, minimo, maximo):
    fuera = [f[columna] for f in filas if f.get(columna) is not None and not minimo <= f[columna] <= maximo]
    if fuera:
        informe.errores.append(
            f"{columna}: {len(fuera)} valores fuera de [{minimo}, {maximo}] (ej. {fuera[0]})"
        )
