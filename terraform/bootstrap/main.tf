terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # El estado de este módulo es LOCAL a propósito: es el que crea el bucket
  # donde vivirá el estado de todo lo demás. Problema del huevo y la gallina.
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      ManagedBy = "terraform"
      Owner     = var.owner
      Module    = "bootstrap"
    }
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. PRESUPUESTO CON ALERTA
#
# Va primero por diseño: si algo se desmadra, quiero enterarme por correo y no
# por la factura. Se crea antes que cualquier recurso que pueda generar coste.
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_budgets_budget" "mensual" {
  name         = "${var.project}-presupuesto-mensual"
  budget_type  = "COST"
  limit_amount = var.presupuesto_mensual
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Aviso temprano: al 50% del límite ya hay algo que no encaja,
  # porque el gasto esperado de este proyecto son céntimos.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.email_alertas]
  }

  # Límite alcanzado.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.email_alertas]
  }

  # Previsión: avisa ANTES de llegar, proyectando el ritmo de gasto actual.
  # Es el que de verdad da margen de reacción.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.email_alertas]
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. BUCKET DE ESTADO REMOTO
#
# Sufijo aleatorio porque los nombres de bucket son únicos a nivel mundial.
# Se usa un aleatorio en lugar del ID de cuenta para no dejarlo escrito en un
# repositorio público.
# ─────────────────────────────────────────────────────────────────────────────

resource "random_id" "sufijo" {
  byte_length = 4
}

resource "aws_s3_bucket" "estado" {
  bucket = "${var.project}-tfstate-${random_id.sufijo.hex}"

  # Este bucket NO se destruye en los teardowns: contiene el estado de toda
  # la infraestructura. Borrarlo dejaría recursos huérfanos imposibles de
  # gestionar con Terraform.
  lifecycle {
    prevent_destroy = true
  }
}

# Versionado: permite recuperar un estado anterior si un apply lo corrompe.
resource "aws_s3_bucket_versioning" "estado" {
  bucket = aws_s3_bucket.estado.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Cifrado en reposo. SSE-S3 basta y no tiene coste; KMS cobraría por petición.
resource "aws_s3_bucket_server_side_encryption_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# El estado puede contener valores sensibles en claro: nada de acceso público.
resource "aws_s3_bucket_public_access_block" "estado" {
  bucket = aws_s3_bucket.estado.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Obliga a que todo acceso viaje cifrado en tránsito.
resource "aws_s3_bucket_policy" "estado_solo_tls" {
  bucket = aws_s3_bucket.estado.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenegarTransporteInseguro"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.estado.arn,
        "${aws_s3_bucket.estado.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.estado]
}

# Limpia versiones antiguas del estado y subidas incompletas.
# Sin esto el bucket crece indefinidamente con cada apply.
resource "aws_s3_bucket_lifecycle_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    id     = "retirar-versiones-antiguas"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
