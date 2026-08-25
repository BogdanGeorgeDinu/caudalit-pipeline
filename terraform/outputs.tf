output "bucket_raw" {
  description = "Bucket del dato crudo. Destino de las Lambdas de ingesta (Fase 4)."
  value       = aws_s3_bucket.datos["raw"].bucket
}

output "bucket_curated" {
  description = "Bucket del dato transformado. Destino del job de Glue (Fase 5)."
  value       = aws_s3_bucket.datos["curated"].bucket
}

output "bucket_athena" {
  description = "Bucket de resultados de consultas."
  value       = aws_s3_bucket.datos["athena"].bucket
}

output "base_datos_glue" {
  description = "Base de datos del catálogo. Aquí registrará la tabla el job de PySpark."
  value       = aws_glue_catalog_database.pipeline.name
}

output "workgroup_athena" {
  description = "Workgroup a usar en la consola de Athena para que aplique el límite de escaneo."
  value       = aws_athena_workgroup.pipeline.name
}

output "rol_lambda_ingesta" {
  description = "ARN del rol de las Lambdas de ingesta (Fase 4)."
  value       = aws_iam_role.lambda_ingesta.arn
}

output "rol_glue_job" {
  description = "ARN del rol del job de Glue (Fase 5)."
  value       = aws_iam_role.glue_job.arn
}
