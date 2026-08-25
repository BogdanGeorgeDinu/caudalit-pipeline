locals {
  buckets = {
    raw = {
      nombre     = "${local.prefijo}-raw-${local.sufijo}"
      versionado = true
      proposito  = "Dato crudo de las APIs sin transformar"
    }
    curated = {
      nombre     = "${local.prefijo}-curated-${local.sufijo}"
      versionado = false
      proposito  = "Parquet particionado por fecha listo para Athena"
    }
    athena = {
      nombre     = "${local.prefijo}-athena-results-${local.sufijo}"
      versionado = false
      proposito  = "Resultados de las consultas de Athena"
    }
  }
}

resource "aws_s3_bucket" "datos" {
  for_each = local.buckets

  bucket = each.value.nombre

  # Sin comas: S3 rechaza con InvalidTag valores de etiqueta que las lleven,
  # aunque el resto de servicios las admiten.
  tags = {
    Capa      = each.key
    Proposito = each.value.proposito
  }
}

resource "aws_s3_bucket_versioning" "datos" {
  for_each = { for k, v in local.buckets : k => v if v.versionado }

  bucket = aws_s3_bucket.datos[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

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
