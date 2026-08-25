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
  description = "Región AWS. Irlanda: más servicios disponibles y precios más predecibles que Madrid."
  type        = string
  default     = "eu-west-1"
}

variable "presupuesto_mensual" {
  description = <<-EOT
    Límite del presupuesto mensual, en USD.
    La cuenta factura en dólares, así que el presupuesto va en la misma moneda
    para que las cifras cuadren con la factura. 5 USD equivalen a unos 4,60 EUR.
    El gasto esperado del proyecto es de céntimos: esta alerta es un cortafuegos,
    no una previsión.
  EOT
  type        = string
  default     = "5"
}

variable "email_alertas" {
  description = "Correo que recibe los avisos del presupuesto. Se define en terraform.tfvars, que no se versiona."
  type        = string
}
