"""Cruza y valida un día de datos crudos sin levantar Spark.

Sirve para dos cosas: comprobar la lógica contra ficheros reales antes de
gastar un DPU, y diagnosticar un día que el job marcó como sospechoso.

    python3 herramientas/revisar_dia.py <carpeta_raw> 2024-03-01
"""

import json
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "glue"))

import calidad  # noqa: E402
import parseo  # noqa: E402
from tiempo import utc_a_local  # noqa: E402

FUENTES = ("ree_demanda", "ree_precio", "clima_temperatura")


def cargar(raiz: pathlib.Path, fuente: str, dia: date):
    ruta = (
        raiz
        / f"fuente={fuente}"
        / f"anio={dia.year:04d}"
        / f"mes={dia.month:02d}"
        / f"dia={dia.day:02d}"
        / "datos.json"
    )
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2

    raiz = pathlib.Path(sys.argv[1]).expanduser()
    dia = date.fromisoformat(sys.argv[2])

    crudos = {f: cargar(raiz, f, dia) for f in FUENTES}
    faltan = [f for f, v in crudos.items() if v is None]
    if faltan:
        print(f"faltan fuentes: {', '.join(faltan)}")

    filas = parseo.unir(
        parseo.demanda(crudos["ree_demanda"]) if crudos["ree_demanda"] else [],
        parseo.precio(crudos["ree_precio"]) if crudos["ree_precio"] else [],
        parseo.temperatura(crudos["clima_temperatura"]) if crudos["clima_temperatura"] else [],
    )

    cabecera = f"{'hora local':>10}  {'UTC':>16}  {'MW':>10}  {'PVPC':>8}  {'spot':>8}  {'°C':>6}"
    print(cabecera)
    print("-" * len(cabecera))
    for f in filas:
        local = utc_a_local(f["momento_utc"])
        print(
            f"{local:%H:%M}".rjust(10)
            + f"  {f['momento_utc']:%Y-%m-%d %H:%M}".rjust(18)
            + f"  {_num(f['demanda_mw'], 1):>10}"
            + f"  {_num(f['precio_pvpc_eur_mwh'], 2):>8}"
            + f"  {_num(f['precio_spot_eur_mwh'], 2):>8}"
            + f"  {_num(f['temperatura_c'], 1):>6}"
        )

    informe = calidad.revisar(filas, dia)
    print()
    print(json.dumps(informe.como_dict(), indent=2, ensure_ascii=False))
    return 0 if informe.valido else 1


def _num(v, decimales):
    return "-" if v is None else f"{v:.{decimales}f}"


if __name__ == "__main__":
    raise SystemExit(main())
