# La tabla la registra el job de PySpark en la Fase 5. No se crea crawler:
# un crawler programado factura DPU sin que nadie lo mire.
resource "aws_glue_catalog_database" "pipeline" {
  name        = replace("${local.prefijo}_catalogo", "-", "_")
  description = "Catálogo del pipeline: demanda, precio y temperatura horarios"

  location_uri = "s3://${aws_s3_bucket.datos["curated"].bucket}/"
}
