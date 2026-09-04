from comun import fecha_objetivo, guardar, log, pedir_json

BASE = "https://apidatos.ree.es/es/datos"

# El endpoint de demanda exige estos parámetros geográficos; sin ellos responde
# 400. El de precios los rechaza. Misma API, dos contratos distintos.
GEO = {
    "geo_trunc": "electric_system",
    "geo_limit": "peninsular",
    "geo_ids": "8741",
}


def handler(event, context):
    dia = fecha_objetivo(event)
    rango = {
        "start_date": f"{dia.isoformat()}T00:00",
        "end_date": f"{dia.isoformat()}T23:59",
        "time_trunc": "hour",
    }
    log("inicio", fuente="ree", fecha=dia.isoformat())

    # Cada respuesta se guarda en cuanto llega, no las dos al final. Son dos
    # peticiones a una API que falla sola: si la segunda agota los reintentos y
    # la Lambda se queda sin tiempo, la primera ya esta a salvo en S3 y solo hay
    # que reintentar la que falta.
    demanda = pedir_json(f"{BASE}/demanda/evolucion", {**rango, **GEO}, "ree_demanda")
    claves = [guardar("ree_demanda", dia, demanda)]

    precio = pedir_json(f"{BASE}/mercados/precios-mercados-tiempo-real", rango, "ree_precio")
    claves.append(guardar("ree_precio", dia, precio))

    log("fin", fuente="ree", fecha=dia.isoformat(), claves=claves)
    return {"fecha": dia.isoformat(), "claves": claves}
