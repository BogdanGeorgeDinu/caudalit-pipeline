from datetime import timedelta

from comun import fecha_objetivo, guardar, log, pedir_json

URL = "https://archive-api.open-meteo.com/v1/archive"

# Madrid. La demanda peninsular no depende solo de Madrid, pero es la referencia
# habitual para el consumo español y evita promediar decenas de estaciones.
LATITUD = 40.4168
LONGITUD = -3.7038


def handler(event, context):
    dia = fecha_objetivo(event)
    log("inicio", fuente="clima", fecha=dia.isoformat())

    # Se pide en UTC, no en Europe/Madrid. La API construye la serie con el
    # desfase vigente el dia de la peticion, no el del dia de los datos: en
    # septiembre, un dia de enero vuelve etiquetado en UTC+2. Pidiendo en UTC
    # las marcas ya son instantes y no hay huso que deducir aguas abajo.
    #
    # Por eso hace falta tambien el dia anterior: el dia local de Madrid empieza
    # a las 22:00 o 23:00 UTC de la vispera. La transformacion recorta la
    # ventana; aqui se guarda crudo lo que devuelve la API.
    datos = pedir_json(
        URL,
        {
            "latitude": LATITUD,
            "longitude": LONGITUD,
            "start_date": (dia - timedelta(days=1)).isoformat(),
            "end_date": dia.isoformat(),
            "hourly": "temperature_2m",
            "timezone": "UTC",
        },
        "openmeteo",
    )

    clave = guardar("clima_temperatura", dia, datos)

    log("fin", fuente="clima", fecha=dia.isoformat(), clave=clave)
    return {"fecha": dia.isoformat(), "claves": [clave]}
