variable "project" {
  description = "Prefijo de nombres y etiqueta Project."
  type        = string
  default     = "caudalit-esios"
}

variable "env" {
  description = "Entorno."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Etiqueta Owner, para desglosar coste por responsable."
  type        = string
  default     = "george"
}

variable "region" {
  description = "Region AWS."
  type        = string
  default     = "eu-west-1"
}

variable "retencion_resultados_athena_dias" {
  description = "Dias que se conservan los CSV de resultados de Athena."
  type        = number
  default     = 30
}

variable "limite_escaneo_athena_bytes" {
  description = "Maximo de bytes escaneados por consulta. 1 GiB."
  type        = number
  default     = 1073741824
}

variable "retencion_logs_dias" {
  description = "Retencion de los grupos de logs de CloudWatch."
  type        = number
  default     = 14
}
