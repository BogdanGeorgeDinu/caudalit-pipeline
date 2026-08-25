output "bucket_estado" {
  description = "Nombre del bucket de estado remoto. Va en el backend.hcl del módulo principal."
  value       = aws_s3_bucket.estado.bucket
}

output "region" {
  description = "Región donde vive el bucket de estado."
  value       = var.region
}

output "siguiente_paso" {
  description = "Qué hacer con estos valores."
  value       = <<-EOT

    Bootstrap completado.

    Bucket de estado: ${aws_s3_bucket.estado.bucket}

    Siguiente paso: crear terraform/backend.hcl con este contenido
    (el archivo está en .gitignore y no se versiona):

        bucket = "${aws_s3_bucket.estado.bucket}"
        key    = "pipeline/terraform.tfstate"
        region = "${var.region}"

    Y después, desde terraform/:

        terraform init -backend-config=backend.hcl

  EOT
}
