"""Glue: raw (JSON) -> curated (parquet particionado).

Envoltorio del job. La transformación vive en `transformacion.py`, que no
depende de Glue y por eso se puede ejecutar y probar en local.

    --fecha 2024-03-01   (opcional; por defecto, ayer)
"""

import sys
from datetime import date, timedelta

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext

from transformacion import con_particiones, log, revisar, transformar


def main():
    args = getResolvedOptions(sys.argv, ["JOB_NAME", "bucket_raw", "bucket_curated", "tabla"])
    fecha = _opcional("fecha")
    dia = date.fromisoformat(fecha) if fecha else date.today() - timedelta(days=1)

    sc = SparkContext.getOrCreate()
    glue = GlueContext(sc)
    spark = glue.spark_session
    job = Job(glue)
    job.init(args["JOB_NAME"], args)

    spark.conf.set("spark.sql.session.timeZone", "UTC")
    # Reprocesar un día debe reemplazar solo su partición, no el histórico.
    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")

    log("inicio", fecha=dia.isoformat(), bucket_raw=args["bucket_raw"])

    filas = transformar(spark, f"s3://{args['bucket_raw']}", dia)
    if filas is None:
        log("fin_sin_datos", fecha=dia.isoformat())
        raise SystemExit(f"no hay ninguna fuente para {dia.isoformat()}")

    filas = filas.cache()
    informe = revisar(filas, dia)
    log("calidad", fecha=dia.isoformat(), **informe)

    if informe["errores"]:
        raise SystemExit(f"calidad: {'; '.join(informe['errores'])}")

    destino = f"s3://{args['bucket_curated']}/{args['tabla']}/"
    (
        con_particiones(filas)
        .repartition(1)
        .write.mode("overwrite")
        .partitionBy("anio", "mes", "dia")
        .parquet(destino)
    )

    log("escrito", fecha=dia.isoformat(), destino=destino, filas=informe["filas"])
    job.commit()


def _opcional(nombre):
    marca = f"--{nombre}"
    if marca in sys.argv:
        return sys.argv[sys.argv.index(marca) + 1]
    return None


if __name__ == "__main__":
    main()
