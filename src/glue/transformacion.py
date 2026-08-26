"""Transformación raw -> curated en PySpark.

Sin dependencias de Glue: se ejecuta igual dentro del job y en una sesión
local de Spark, que es lo que permite probarla.
"""

import json

from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

from calidad import COLUMNAS, DEMANDA_MAX_MW, DEMANDA_MIN_MW, TEMPERATURA_MAX_C, TEMPERATURA_MIN_C
from tiempo import calendario, horas_esperadas

FORMATO_REE = "yyyy-MM-dd'T'HH:mm:ss.SSSXXX"
FUENTES = ("ree_demanda", "ree_precio", "clima_temperatura")


def log(evento, **campos):
    print(json.dumps({"evento": evento, **campos}, ensure_ascii=False, default=str))


def ruta(base, fuente, dia):
    """Vale igual para `s3://bucket` que para una carpeta local."""
    return (
        f"{base}/fuente={fuente}"
        f"/anio={dia.year:04d}/mes={dia.month:02d}/dia={dia.day:02d}/datos.json"
    )


def leer_json(spark, base, fuente, dia):
    """Devuelve None si la fuente no está: un hueco no debe tumbar el job."""
    origen = ruta(base, fuente, dia)
    try:
        df = spark.read.option("multiLine", "true").json(origen)
    except Exception as e:  # noqa: BLE001 - cualquier fallo de lectura es un hueco
        log("fuente_ausente", fuente=fuente, ruta=origen, motivo=str(e))
        return None
    if not df.head(1):
        log("fuente_vacia", fuente=fuente, ruta=origen)
        return None
    return df


def serie(df, titulo):
    """Extrae una serie de `included` y la aplana a (momento_utc, valor)."""
    return (
        df.select(F.explode("included").alias("bloque"))
        .where(F.col("bloque.attributes.title") == titulo)
        .select(F.explode("bloque.attributes.values").alias("v"))
        .select(
            F.to_timestamp(F.col("v.datetime"), FORMATO_REE).alias("momento_utc"),
            F.col("v.value").cast("double").alias("valor"),
        )
        .where(F.col("momento_utc").isNotNull())
    )


def tabla_demanda(df):
    return serie(df, "Demanda").withColumnRenamed("valor", "demanda_mw")


def tabla_precio(df):
    pvpc = serie(df, "PVPC").withColumnRenamed("valor", "precio_pvpc_eur_mwh")
    spot = serie(df, "Precio mercado spot").withColumnRenamed("valor", "precio_spot_eur_mwh")
    return pvpc.join(spot, on="momento_utc", how="full_outer")


def tabla_temperatura(spark, df, dia):
    """Open-Meteo entrega hora local sin desfase.

    Se cruza contra el calendario del día en vez de convertir con
    `to_utc_timestamp`: las reglas quedan en `tiempo.calendario`, que está
    probado, y el resultado no depende de la configuración de Spark.
    """
    esquema = StructType(
        [
            StructField("hora_local", StringType(), False),
            StructField("momento_utc", TimestampType(), False),
        ]
    )
    cal = spark.createDataFrame(calendario(dia), schema=esquema)

    horas = (
        df.select(F.arrays_zip("hourly.time", "hourly.temperature_2m").alias("pares"))
        .select(F.explode("pares").alias("p"))
        .select(
            F.col("p.time").alias("hora_local"),
            F.col("p.temperature_2m").cast("double").alias("temperatura_c"),
        )
    )

    return (
        horas.join(F.broadcast(cal), on="hora_local", how="inner")
        .groupBy("momento_utc")
        .agg(F.first("temperatura_c", ignorenulls=True).alias("temperatura_c"))
    )


def cruzar(*tablas):
    """Full outer entre las fuentes presentes: un hueco queda como nulo."""
    filas = None
    for df in tablas:
        if df is None:
            continue
        filas = df if filas is None else filas.join(df, on="momento_utc", how="full_outer")
    return filas


def completar_columnas(filas):
    """Si faltó una fuente, su columna no existe: se crea vacía para que el
    esquema del parquet sea siempre el mismo."""
    for columna in COLUMNAS:
        if columna not in filas.columns:
            filas = filas.withColumn(columna, F.lit(None).cast("double"))
    return filas.select("momento_utc", *COLUMNAS)


def revisar(filas, dia):
    """Mismas reglas que `calidad.revisar`, evaluadas sobre el DataFrame."""
    agregados = (
        filas.agg(
            F.count("*").alias("filas"),
            F.countDistinct("momento_utc").alias("instantes"),
            *[F.sum(F.col(c).isNull().cast("int")).alias(f"nulos_{c}") for c in COLUMNAS],
            F.sum(
                ((F.col("demanda_mw") < DEMANDA_MIN_MW) | (F.col("demanda_mw") > DEMANDA_MAX_MW)).cast("int")
            ).alias("demanda_fuera_rango"),
            F.sum(
                ((F.col("temperatura_c") < TEMPERATURA_MIN_C) | (F.col("temperatura_c") > TEMPERATURA_MAX_C)).cast("int")
            ).alias("temperatura_fuera_rango"),
        )
        .collect()[0]
        .asDict()
    )

    esperadas = horas_esperadas(dia)
    errores, avisos = [], []

    if agregados["filas"] == 0:
        errores.append("sin filas")
    if agregados["filas"] != agregados["instantes"]:
        errores.append("instantes duplicados")
    if agregados["filas"] and agregados["nulos_demanda_mw"] == agregados["filas"]:
        errores.append("demanda_mw completamente vacia")
    for columna in ("demanda", "temperatura"):
        fuera = agregados[f"{columna}_fuera_rango"]
        if fuera:
            errores.append(f"{columna}: {fuera} valores fuera de rango")
    if agregados["filas"] != esperadas:
        avisos.append(f"{agregados['filas']} filas frente a {esperadas} esperadas")

    return {**agregados, "filas_esperadas": esperadas, "errores": errores, "avisos": avisos}


def con_particiones(filas):
    """Añade momento local y las tres columnas de partición.

    Cadenas con cero delante, igual que la capa raw: la proyección de
    particiones de Athena espera `mes=03`, no `mes=3`.
    """
    return (
        filas.withColumn("momento_local", F.from_utc_timestamp("momento_utc", "Europe/Madrid"))
        .withColumn("anio", F.date_format("momento_local", "yyyy"))
        .withColumn("mes", F.date_format("momento_local", "MM"))
        .withColumn("dia", F.date_format("momento_local", "dd"))
    )


def transformar(spark, base_raw, dia):
    """Lee las tres fuentes de un día y devuelve las filas cruzadas."""
    crudos = {f: leer_json(spark, base_raw, f, dia) for f in FUENTES}

    filas = cruzar(
        tabla_demanda(crudos["ree_demanda"]) if crudos["ree_demanda"] is not None else None,
        tabla_precio(crudos["ree_precio"]) if crudos["ree_precio"] is not None else None,
        tabla_temperatura(spark, crudos["clima_temperatura"], dia)
        if crudos["clima_temperatura"] is not None
        else None,
    )
    return completar_columnas(filas) if filas is not None else None
