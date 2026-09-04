locals {
  funciones = {
    ree = {
      nombre      = "${local.prefijo}-ingesta-ree"
      handler     = "ree.handler"
      descripcion = "Demanda y precio horarios desde apidatos.ree.es"
    }
    clima = {
      nombre      = "${local.prefijo}-ingesta-clima"
      handler     = "openmeteo.handler"
      descripcion = "Temperatura horaria desde Open-Meteo"
    }
  }
}

# Un unico zip para las dos funciones: comparten comun.py y cambia el handler.
# Evita duplicar codigo sin tener que mantener una capa para 80 lineas.
data "archive_file" "ingesta" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas"
  output_path = "${path.module}/.build/ingesta.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_lambda_function" "ingesta" {
  for_each = local.funciones

  function_name = each.value.nombre
  description   = each.value.descripcion
  role          = aws_iam_role.lambda_ingesta.arn

  filename         = data.archive_file.ingesta.output_path
  source_code_hash = data.archive_file.ingesta.output_base64sha256

  runtime = "python3.13"
  handler = each.value.handler

  # Dimensionado, no a ojo. Con 6 intentos, timeout HTTP de 25 s y esperas de
  # 1,5+3+6+12+24 mas jitter, el peor caso de UNA peticion son 201,5 s. La
  # Lambda de REE hace dos, o sea 403 s: con los 300 s de antes se moria antes
  # de agotar los reintentos de la segunda. Se factura por ms consumidos, no
  # por el timeout configurado, asi que subirlo no cuesta nada.
  timeout     = 600
  memory_size = 256

  environment {
    variables = {
      BUCKET_RAW   = aws_s3_bucket.datos["raw"].bucket
      INTENTOS     = "6"
      ESPERA_BASE  = "1.5"
      TIMEOUT_HTTP = "25"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingesta]
}

resource "aws_cloudwatch_log_group" "ingesta" {
  for_each = local.funciones

  name              = "/aws/lambda/${each.value.nombre}"
  retention_in_days = var.retencion_logs_dias
}
