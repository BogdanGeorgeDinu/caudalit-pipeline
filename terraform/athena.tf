resource "aws_athena_workgroup" "pipeline" {
  name        = "${local.prefijo}-workgroup"
  description = "Consultas del pipeline con límite de escaneo por consulta"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    # Aborta la consulta al superar el limite, antes de seguir facturando.
    bytes_scanned_cutoff_per_query = var.limite_escaneo_athena_bytes

    result_configuration {
      output_location = "s3://${aws_s3_bucket.datos["athena"].bucket}/resultados/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  force_destroy = true
}
