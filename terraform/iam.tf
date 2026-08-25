# ─────────────────────────────────────────────────────────────────────────────
# IAM CON PERMISOS MÍNIMOS
#
# Ni una sola política gestionada de AWS con comodines. Cada rol puede hacer
# exactamente lo que necesita, sobre los recursos concretos que necesita.
#
# Es más trabajo que poner AdministratorAccess y seguir, pero es la diferencia
# entre "funciona" y "funciona y no es un agujero".
# ─────────────────────────────────────────────────────────────────────────────

# ── Rol de las Lambdas de ingesta ────────────────────────────────────────────
# Solo escriben en raw/. No pueden leer nada, ni tocar curated.

data "aws_iam_policy_document" "lambda_asumir" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_ingesta" {
  name               = "${local.prefijo}-lambda-ingesta"
  description        = "Ingesta desde las APIs de REE y Open-Meteo hacia S3 raw"
  assume_role_policy = data.aws_iam_policy_document.lambda_asumir.json
}

data "aws_iam_policy_document" "lambda_ingesta" {
  # Escribir el dato crudo. Solo PutObject: no necesita leer ni borrar.
  statement {
    sid       = "EscribirEnRaw"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.datos["raw"].arn}/*"]
  }

  # Sus propios logs, restringidos a su grupo de logs.
  statement {
    sid    = "EscribirSusLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda_ingesta.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda_ingesta" {
  name   = "${local.prefijo}-lambda-ingesta"
  role   = aws_iam_role.lambda_ingesta.id
  policy = data.aws_iam_policy_document.lambda_ingesta.json
}

# El grupo de logs se crea aquí y no se deja a la Lambda: así lleva retención
# definida. Los que crea Lambda sola no caducan nunca, y se pagan para siempre.
resource "aws_cloudwatch_log_group" "lambda_ingesta" {
  name              = "/aws/lambda/${local.prefijo}-ingesta"
  retention_in_days = var.retencion_logs_dias
}

# ── Rol del job de Glue ──────────────────────────────────────────────────────
# Lee raw, escribe curated, y registra el esquema en el catálogo.

data "aws_iam_policy_document" "glue_asumir" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue_job" {
  name               = "${local.prefijo}-glue-job"
  description        = "Transformación raw a curated con PySpark"
  assume_role_policy = data.aws_iam_policy_document.glue_asumir.json
}

data "aws_iam_policy_document" "glue_job" {
  # Leer el crudo. Solo lectura: un job de transformación no borra el origen.
  statement {
    sid       = "LeerRaw"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.datos["raw"].arn}/*"]
  }

  statement {
    sid       = "ListarRaw"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.datos["raw"].arn]
  }

  # Escribir el resultado. DeleteObject es necesario para poder reescribir
  # una partición al reprocesar un día.
  statement {
    sid    = "EscribirCurated"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.datos["curated"].arn}/*"]
  }

  statement {
    sid       = "ListarCurated"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.datos["curated"].arn]
  }

  # Catálogo: solo sobre nuestra base de datos, no sobre todo el catálogo.
  statement {
    sid    = "GestionarCatalogo"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchCreatePartition",
      "glue:BatchGetPartition",
    ]
    resources = [
      "arn:aws:glue:${var.region}:${local.sufijo}:catalog",
      "arn:aws:glue:${var.region}:${local.sufijo}:database/${aws_glue_catalog_database.pipeline.name}",
      "arn:aws:glue:${var.region}:${local.sufijo}:table/${aws_glue_catalog_database.pipeline.name}/*",
    ]
  }

  statement {
    sid    = "EscribirSusLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:AssociateKmsKey",
    ]
    resources = ["arn:aws:logs:${var.region}:${local.sufijo}:log-group:/aws-glue/*"]
  }
}

resource "aws_iam_role_policy" "glue_job" {
  name   = "${local.prefijo}-glue-job"
  role   = aws_iam_role.glue_job.id
  policy = data.aws_iam_policy_document.glue_job.json
}
