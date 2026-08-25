# ─────────────────────────────────────────────────────────────────────────────
# WORKGROUP DE ATHENA
#
# Athena factura por terabyte escaneado. El riesgo real no es el uso normal
# —aquí los datos son kilobytes— sino una consulta mal escrita sobre una tabla
# sin particionar, o un SELECT * sobre un histórico entero.
#
# El workgroup es donde se pone el freno: límite de bytes por consulta,
# ubicación de resultados forzada y cifrado obligatorio.
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_athena_workgroup" "pipeline" {
  name        = "${local.prefijo}-workgroup"
  description = "Consultas del pipeline, con límite de escaneo por consulta"
  state       = "ENABLED"

  configuration {
    # Impide que alguien apunte los resultados a otro sitio y se salte
    # el cifrado o el ciclo de vida.
    enforce_workgroup_configuration = true

    publish_cloudwatch_metrics_enabled = true

    # EL FRENO DE MANO: una consulta que supere este límite se aborta
    # automáticamente antes de facturar más.
    bytes_scanned_cutoff_per_query = var.limite_escaneo_athena_bytes

    result_configuration {
      output_location = "s3://${aws_s3_bucket.datos["athena"].bucket}/resultados/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  # Al destruir, borra también las consultas guardadas del workgroup.
  force_destroy = true
}
