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
  statement {
    sid       = "EscribirEnRaw"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.datos["raw"].arn}/*"]
  }

  statement {
    sid    = "EscribirSusLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [for g in aws_cloudwatch_log_group.ingesta : "${g.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda_ingesta" {
  name   = "${local.prefijo}-lambda-ingesta"
  role   = aws_iam_role.lambda_ingesta.id
  policy = data.aws_iam_policy_document.lambda_ingesta.json
}

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

  # DeleteObject permite reescribir una partición al reprocesar un día.
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

  # Glue descarga el script y los modulos con este mismo rol: sin esto el job
  # falla al arrancar, antes de ejecutar una sola linea.
  statement {
    sid       = "LeerArtefactos"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.datos["artefactos"].arn}/*"]
  }

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
