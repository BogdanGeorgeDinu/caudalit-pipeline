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

  # Holgado para absorber la espera de los reintentos. Se factura por ms
  # consumidos, no por el timeout configurado.
  timeout     = 300
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
