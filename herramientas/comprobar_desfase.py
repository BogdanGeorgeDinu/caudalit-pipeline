"""Comprueba contra Open-Meteo que la alineacion horaria es correcta.

Es la herramienta que destapo el fallo de la Fase 5. Pide el mismo dia dos
veces, en Europe/Madrid y en UTC, y compara las dos lecturas posibles de la
etiqueta contra la verdad de referencia:

  a) interpretarla como hora local de Madrid  -> lo que hacia la primera
     version, y lo que desplaza el dato una hora en invierno
  b) restarle el utc_offset_seconds declarado -> correcto siempre

La ingesta actual evita la disyuntiva pidiendo `timezone=UTC`, pero conviene
poder repetir la medicion: si Open-Meteo cambia de criterio, esto lo detecta.

    python3 herramientas/comprobar_desfase.py
    python3 herramientas/comprobar_desfase.py 2024-01-15 2024-07-15
"""

import json
import pathlib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "glue"))

MADRID = ZoneInfo("Europe/Madrid")
URL = (
    "https://archive-api.open-meteo.com/v1/archive"
    "?latitude=40.4168&longitude=-3.7038"
    "&start_date={dia}&end_date={dia}&hourly=temperature_2m&timezone={tz}"
)
DIAS_POR_DEFECTO = ["2024-03-01", "2024-01-15", "2024-07-15"]


def pedir(dia, tz):
    with urllib.request.urlopen(URL.format(dia=dia, tz=tz), timeout=30) as r:
        return json.load(r)


def comprobar(dia):
    local, utc = pedir(dia, "Europe%2FMadrid"), pedir(dia, "UTC")
    desfase = local["utc_offset_seconds"]

    verdad = {
        datetime.fromisoformat(t).replace(tzinfo=timezone.utc): v
        for t, v in zip(utc["hourly"]["time"], utc["hourly"]["temperature_2m"])
    }
    pares = list(zip(local["hourly"]["time"], local["hourly"]["temperature_2m"]))

    como_madrid = {
        datetime.fromisoformat(t).replace(tzinfo=MADRID).astimezone(timezone.utc): v
        for t, v in pares
    }
    restando = {
        datetime.fromisoformat(t).replace(tzinfo=timezone.utc) - timedelta(seconds=desfase): v
        for t, v in pares
    }

    def fallos(cand):
        return sum(1 for k, v in cand.items() if k in verdad and verdad[k] != v)

    return desfase, len(verdad), fallos(como_madrid), fallos(restando)


def main():
    dias = sys.argv[1:] or DIAS_POR_DEFECTO
    print(f"{'dia':<12}{'offset':>8}{'como hora de Madrid':>22}{'restando el campo':>20}")
    print("-" * 62)

    problemas = 0
    for dia in dias:
        desfase, total, mal_madrid, mal_restando = comprobar(dia)
        print(f"{dia:<12}{desfase:>8}{f'{mal_madrid} de {total} mal':>22}{f'{mal_restando} de {total} mal':>20}")
        problemas += mal_restando

    print()
    print("Si la ultima columna no es cero, Open-Meteo ha dejado de ser coherente")
    print("con el desfase que declara y hay que revisar la ingesta.")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
