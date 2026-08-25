# ─────────────────────────────────────────────────────────────────────────────
# CATÁLOGO DE DATOS
#
# La base de datos de Glue es solo metadatos: no almacena nada y no cuesta
# nada. Es el índice que permite a Athena consultar los parquet de S3 como si
# fueran tablas SQL.
#
# En la Fase 5 el job de PySpark registrará aquí la tabla al escribir curated.
# NO se crea un crawler: un crawler programado es la forma más habitual de
# gastar dinero en Glue sin darse cuenta. La tabla la define el propio job.
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_glue_catalog_database" "pipeline" {
  name        = replace("${local.prefijo}_catalogo", "-", "_")
  description = "Catálogo del pipeline: demanda, precio y temperatura horarios"

  # Ubicación por defecto de las tablas de esta base de datos.
  location_uri = "s3://${aws_s3_bucket.datos["curated"].bucket}/"
}
