# La tabla la declara Terraform, no un crawler: un crawler programado factura
# DPU sin que nadie lo mire, y el esquema aquí es fijo y conocido.
resource "aws_glue_catalog_database" "pipeline" {
  name        = replace("${local.prefijo}_catalogo", "-", "_")
  description = "Catálogo del pipeline: demanda, precio y temperatura horarios"

  location_uri = "s3://${aws_s3_bucket.datos["curated"].bucket}/"
}

locals {
  tabla_curated = "demanda_precio_temperatura"
  ruta_curated  = "s3://${aws_s3_bucket.datos["curated"].bucket}/${local.tabla_curated}"
}

data "archive_file" "glue_modulos" {
  type        = "zip"
  output_path = "${path.module}/.build/glue_modulos.zip"

  dynamic "source" {
    for_each = toset(["tiempo.py", "parseo.py", "calidad.py", "transformacion.py"])

    content {
      content  = file("${path.module}/../src/glue/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.datos["artefactos"].id
  key    = "glue/job_curated.py"
  source = "${path.module}/../src/glue/job_curated.py"
  etag   = filemd5("${path.module}/../src/glue/job_curated.py")
}

resource "aws_s3_object" "glue_modulos" {
  bucket = aws_s3_bucket.datos["artefactos"].id
  key    = "glue/glue_modulos.zip"
  source = data.archive_file.glue_modulos.output_path
  etag   = data.archive_file.glue_modulos.output_md5
}

resource "aws_glue_job" "curated" {
  name        = "${local.prefijo}-curated"
  description = "Cruza demanda, precio y temperatura por hora y escribe parquet particionado"
  role_arn    = aws_iam_role.glue_job.arn

  glue_version = "5.0"

  # El mínimo de Glue. Con 24 filas por día sobra: el coste está en arrancar
  # el cluster, no en procesar.
  worker_type       = "G.1X"
  number_of_workers = 2

  # Tope de gasto por si una ejecución se queda colgada. Glue factura por
  # DPU-hora y no tiene capa gratuita.
  timeout = 15

  # Sin reintentos: reintentar dobla el coste sin diagnosticar nada. La
  # orquestación de la Fase 7 decidirá cuándo repetir.
  max_retries = 0

  command {
    script_location = "s3://${aws_s3_bucket.datos["artefactos"].id}/${aws_s3_object.glue_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--bucket_raw"     = aws_s3_bucket.datos["raw"].bucket
    "--bucket_curated" = aws_s3_bucket.datos["curated"].bucket
    "--tabla"          = local.tabla_curated

    "--extra-py-files" = "s3://${aws_s3_bucket.datos["artefactos"].id}/${aws_s3_object.glue_modulos.key}"

    # Grupo propio para que la retención la fije Terraform. Los que crea Glue
    # por su cuenta no caducan nunca.
    "--enable-continuous-cloudwatch-log" = "true"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.glue_curated.name

    "--enable-metrics"               = "true"
    "--enable-observability-metrics" = "true"
    "--job-language"                 = "python"

    # Marcadores desactivados: el día a procesar llega por parámetro y la
    # partición se sobrescribe, así que reprocesar debe ser idempotente.
    "--job-bookmark-option" = "job-bookmark-disable"
  }
}

resource "aws_cloudwatch_log_group" "glue_curated" {
  name              = "/aws-glue/jobs/${local.prefijo}-curated"
  retention_in_days = var.retencion_logs_dias
}

# Glue escribe la salida y los errores del driver y los ejecutores en estos dos
# grupos, aparte del continuo de arriba. Se declaran aqui por lo mismo que el
# resto: los que crea AWS por su cuenta nacen sin retencion y se pagan para
# siempre. Y el rol no tiene logs:CreateLogGroup a proposito, asi que si no
# existen no hay salida del driver, que es justo lo que se mira cuando el job
# falla.
resource "aws_cloudwatch_log_group" "glue_salida" {
  for_each = toset(["output", "error"])

  name              = "/aws-glue/jobs/${each.value}"
  retention_in_days = var.retencion_logs_dias
}

# Proyección de particiones: Athena deduce las particiones del patrón de la
# ruta. Sin crawler y sin MSCK REPAIR, que son las dos formas habituales de
# pagar DPU o de que el catálogo se quede desfasado.
resource "aws_glue_catalog_table" "curated" {
  name          = local.tabla_curated
  database_name = aws_glue_catalog_database.pipeline.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification        = "parquet"
    EXTERNAL              = "TRUE"
    "parquet.compression" = "SNAPPY"

    "projection.enabled"    = "true"
    "projection.anio.type"  = "integer"
    "projection.anio.range" = "2024,2030"
    "projection.mes.type"   = "integer"
    "projection.mes.range"  = "1,12"
    "projection.mes.digits" = "2"
    "projection.dia.type"   = "integer"
    "projection.dia.range"  = "1,31"
    "projection.dia.digits" = "2"

    "storage.location.template" = "${local.ruta_curated}/anio=$${anio}/mes=$${mes}/dia=$${dia}"
  }

  partition_keys {
    name = "anio"
    type = "string"
  }
  partition_keys {
    name = "mes"
    type = "string"
  }
  partition_keys {
    name = "dia"
    type = "string"
  }

  storage_descriptor {
    location      = local.ruta_curated
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name    = "momento_utc"
      type    = "timestamp"
      comment = "Instante en UTC. Clave del cruce entre las tres fuentes."
    }
    columns {
      name    = "demanda_mw"
      type    = "double"
      comment = "Demanda peninsular en megavatios"
    }
    columns {
      name    = "precio_pvpc_eur_mwh"
      type    = "double"
      comment = "Precio voluntario para el pequeño consumidor, EUR/MWh"
    }
    columns {
      name    = "precio_spot_eur_mwh"
      type    = "double"
      comment = "Precio del mercado diario, EUR/MWh"
    }
    columns {
      name    = "temperatura_c"
      type    = "double"
      comment = "Temperatura a 2 metros en Madrid, grados Celsius"
    }
    columns {
      name    = "momento_local"
      type    = "timestamp"
      comment = "Mismo instante en hora de Madrid, para leer la hora punta"
    }
  }
}
