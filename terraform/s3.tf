# ─────────────────────────────────────────────────────────────────────────────
# LOS TRES BUCKETS DEL PIPELINE
#
#   raw      · el JSON tal cual lo devuelve la API, sin tocar
#   curated  · parquet particionado, listo para consultar
#   athena   · resultados de las consultas (Athena los exige)
#
# Todos comparten la misma configuración de seguridad, así que se define una
# vez con for_each en lugar de repetirla tres veces.
# ─────────────────────────────────────────────────────────────────────────────

locals {
  buckets = {
    raw = {
      nombre     = "${local.prefijo}-raw-${local.sufijo}"
      versionado = true # el dato crudo es el seguro ante un fallo de lógica
      proposito  = "Dato crudo de las APIs, sin transformar"
    }
    curated = {
      nombre     = "${local.prefijo}-curated-${local.sufijo}"
      versionado = false # se regenera desde raw; versionar solo ocuparía sitio
      proposito  = "Parquet particionado por fecha, listo para Athena"
    }
    athena = {
      nombre     = "${local.prefijo}-athena-results-${local.sufijo}"
      versionado = false # resultados desechables
      proposito  = "Resultados de las consultas de Athena"
    }
  }
}

resource "aws_s3_bucket" "datos" {
  for_each = local.buckets

  bucket = each.value.nombre

  tags = {
    Capa      = each.key
    Proposito = each.value.proposito
  }
}

# Solo se crea el recurso en los buckets que sí lo necesitan. Poner
# status = "Disabled" explícitamente solo es válido si el bucket nunca tuvo
# versionado, así que es preferible no declarar el recurso en absoluto.
resource "aws_s3_bucket_versioning" "datos" {
  for_each = { for k, v in local.buckets : k => v if v.versionado }

  bucket = aws_s3_bucket.datos[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 en lugar de KMS: aquí basta y no cobra por petición.
resource "aws_s3_bucket_server_side_encryption_configuration" "datos" {
  for_each = local.buckets

  bucket = aws_s3_bucket.datos[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "datos" {
  for_each = local.buckets

  bucket = aws_s3_bucket.datos[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Deniega cualquier acceso que no viaje por TLS.
resource "aws_s3_bucket_policy" "solo_tls" {
  for_each = local.buckets

  bucket = aws_s3_bucket.datos[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenegarTransporteInseguro"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.datos[each.key].arn,
        "${aws_s3_bucket.datos[each.key].arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.datos]
}

# Ciclo de vida: limpia subidas incompletas en los tres, y además caduca
# los resultados de Athena, que si no se acumulan sin control.
resource "aws_s3_bucket_lifecycle_configuration" "datos" {
  for_each = local.buckets

  bucket = aws_s3_bucket.datos[each.key].id

  rule {
    id     = "abortar-subidas-incompletas"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = each.key == "athena" ? [1] : []

    content {
      id     = "caducar-resultados"
      status = "Enabled"

      filter {}

      expiration {
        days = var.retencion_resultados_athena_dias
      }
    }
  }
}
