variable "project" {
  description = "Prefijo de nombres y etiqueta Project de todos los recursos."
  type        = string
  default     = "caudalit-esios"
}

variable "env" {
  description = "Entorno. Este proyecto solo usa dev."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Etiqueta Owner, para poder desglosar el coste por responsable."
  type        = string
  default     = "george"
}

variable "region" {
  description = "Región AWS."
  type        = string
  default     = "eu-west-1"
}

variable "retencion_resultados_athena_dias" {
  description = <<-EOT
    Días que se conservan los resultados de consultas de Athena.
    Athena escribe un CSV en S3 por cada consulta. Sin caducidad, ese bucket
    crece indefinidamente con basura que nadie vuelve a mirar.
  EOT
  type        = number
  default     = 30
}

variable "limite_escaneo_athena_bytes" {
  description = <<-EOT
    Máximo de bytes que puede escanear una sola consulta de Athena.
    Athena factura por TB escaneado, así que una consulta mal escrita sobre una
    tabla sin particionar puede costar dinero de verdad. Este límite la aborta
    antes de que eso pase: es un freno de mano, no una optimización.
    1 GiB es holgadísimo para este proyecto, donde los datos son kilobytes.
  EOT
  type        = number
  default     = 1073741824
}

variable "retencion_logs_dias" {
  description = "Días de retención de los logs de CloudWatch. Sin esto se guardan para siempre y se pagan para siempre."
  type        = number
  default     = 14
}
