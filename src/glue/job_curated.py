"""Glue: raw (JSON) -> curated (parquet particionado).

Cruza demanda, precio y temperatura por hora y escribe un día por ejecución.

    --fecha 2024-03-01   (opcional; por defecto, ayer)
"""

import json
import sys
from datetime import date, timedelta

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

from calidad import COLUMNAS, DEMANDA_MAX_MW, DEMANDA_MIN_MW, TEMPERATURA_MAX_C, TEMPERATURA_MIN_C
from tiempo import calendario, horas_esperadas

FORMATO_REE = "yyyy-MM-dd'T'HH:mm:ss.SSSXXX"
FUENTES = ("ree_demanda", "ree_precio", "clima_temperatura")


def log(evento, **campos):
    print(json.dumps({"evento": evento, **campos}, ensure_ascii=False, default=str))


def ruta(bucket, fuente, dia):
    return (
        f"s3://{bucket}/fuente={fuente}"
        f"/anio={dia.year:04d}/mes={dia.month:02d}/dia={dia.day:02d}/datos.json"
    )


def leer_json(spark, bucket, fuente, dia):
    """Devuelve None si la fuente no está: un hueco no debe tumbar el job."""
    origen = ruta(bucket, fuente, dia)
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
    """Extrae una serie de `included` y la aplana a (datetime, value)."""
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
        df.select(
            F.arrays_zip("hourly.time", "hourly.temperature_2m").alias("pares")
        )
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


def cruzar(demanda, precio, temperatura):
    filas = None
    for df in (demanda, precio, temperatura):
        if df is None:
            continue
        filas = df if filas is None else filas.join(df, on="momento_utc", how="full_outer")
    return filas


def revisar(filas, dia):
    """Mismas reglas que `calidad.revisar`, evaluadas sobre el DataFrame."""
    agregados = filas.agg(
        F.count("*").alias("filas"),
        F.countDistinct("momento_utc").alias("instantes"),
        *[F.sum(F.col(c).isNull().cast("int")).alias(f"nulos_{c}") for c in COLUMNAS],
        F.sum(
            ((F.col("demanda_mw") < DEMANDA_MIN_MW) | (F.col("demanda_mw") > DEMANDA_MAX_MW)).cast("int")
        ).alias("demanda_fuera_rango"),
        F.sum(
            ((F.col("temperatura_c") < TEMPERATURA_MIN_C) | (F.col("temperatura_c") > TEMPERATURA_MAX_C)).cast("int")
        ).alias("temperatura_fuera_rango"),
    ).collect()[0].asDict()

    esperadas = horas_esperadas(dia)
    errores, avisos = [], []

    if agregados["filas"] == 0:
        errores.append("sin filas")
    if agregados["filas"] != agregados["instantes"]:
        errores.append("instantes duplicados")
    if agregados["nulos_demanda_mw"] == agregados["filas"] and agregados["filas"]:
        errores.append("demanda_mw completamente vacia")
    for columna in ("demanda", "temperatura"):
        if agregados[f"{columna}_fuera_rango"]:
            errores.append(f"{columna}: {agregados[f'{columna}_fuera_rango']} valores fuera de rango")
    if agregados["filas"] != esperadas:
        avisos.append(f"{agregados['filas']} filas frente a {esperadas} esperadas")

    return {**agregados, "filas_esperadas": esperadas, "errores": errores, "avisos": avisos}


def main():
    args = getResolvedOptions(
        sys.argv,
        ["JOB_NAME", "bucket_raw", "bucket_curated", "tabla"] ,
    )
    fecha_arg = _opcional("fecha")
    dia = date.fromisoformat(fecha_arg) if fecha_arg else date.today() - timedelta(days=1)

    sc = SparkContext.getOrCreate()
    glue = GlueContext(sc)
    spark = glue.spark_session
    job = Job(glue)
    job.init(args["JOB_NAME"], args)

    spark.conf.set("spark.sql.session.timeZone", "UTC")
    # Reprocesar un día debe reemplazar solo su partición, no el histórico.
    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")

    log("inicio", fecha=dia.isoformat(), bucket_raw=args["bucket_raw"])

    crudos = {f: leer_json(spark, args["bucket_raw"], f, dia) for f in FUENTES}

    filas = cruzar(
        tabla_demanda(crudos["ree_demanda"]) if crudos["ree_demanda"] is not None else None,
        tabla_precio(crudos["ree_precio"]) if crudos["ree_precio"] is not None else None,
        tabla_temperatura(spark, crudos["clima_temperatura"], dia)
        if crudos["clima_temperatura"] is not None
        else None,
    )

    if filas is None:
        log("fin_sin_datos", fecha=dia.isoformat())
        raise SystemExit(f"no hay ninguna fuente para {dia.isoformat()}")

    filas = _completar_columnas(filas).cache()
    informe = revisar(filas, dia)
    log("calidad", fecha=dia.isoformat(), **informe)

    if informe["errores"]:
        raise SystemExit(f"calidad: {'; '.join(informe['errores'])}")

    destino = f"s3://{args['bucket_curated']}/{args['tabla']}/"
    (
        filas.withColumn("momento_local", F.from_utc_timestamp("momento_utc", "Europe/Madrid"))
        # Cadenas con cero delante, igual que la capa raw: la proyección de
        # particiones de Athena espera `mes=03`, no `mes=3`.
        .withColumn("anio", F.date_format("momento_local", "yyyy"))
        .withColumn("mes", F.date_format("momento_local", "MM"))
        .withColumn("dia", F.date_format("momento_local", "dd"))
        .repartition(1)
        .write.mode("overwrite")
        .partitionBy("anio", "mes", "dia")
        .parquet(destino)
    )

    log("escrito", fecha=dia.isoformat(), destino=destino, filas=informe["filas"])
    job.commit()


def _completar_columnas(filas):
    """Si faltó una fuente, su columna no existe: se crea vacía para que el
    esquema del parquet sea siempre el mismo."""
    for columna in COLUMNAS:
        if columna not in filas.columns:
            filas = filas.withColumn(columna, F.lit(None).cast("double"))
    return filas.select("momento_utc", *COLUMNAS)


def _opcional(nombre):
    marca = f"--{nombre}"
    if marca in sys.argv:
        return sys.argv[sys.argv.index(marca) + 1]
    return None


if __name__ == "__main__":
    main()
