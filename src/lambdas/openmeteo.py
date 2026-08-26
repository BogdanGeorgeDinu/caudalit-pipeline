from comun import fecha_objetivo, guardar, log, pedir_json

URL = "https://archive-api.open-meteo.com/v1/archive"

# Madrid. La demanda peninsular no depende solo de Madrid, pero es la referencia
# habitual para el consumo español y evita promediar decenas de estaciones.
LATITUD = 40.4168
LONGITUD = -3.7038


def handler(event, context):
    dia = fecha_objetivo(event)
    log("inicio", fuente="clima", fecha=dia.isoformat())

    datos = pedir_json(
        URL,
        {
            "latitude": LATITUD,
            "longitude": LONGITUD,
            "start_date": dia.isoformat(),
            "end_date": dia.isoformat(),
            "hourly": "temperature_2m",
            "timezone": "Europe/Madrid",
        },
        "openmeteo",
    )

    clave = guardar("clima_temperatura", dia, datos)

    log("fin", fuente="clima", fecha=dia.isoformat(), clave=clave)
    return {"fecha": dia.isoformat(), "claves": [clave]}
