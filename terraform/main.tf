terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Configuración parcial: el nombre real del bucket vive en backend.hcl,
  # que no se versiona porque es específico de esta cuenta.
  #
  #   terraform init -backend-config=backend.hcl
  #
  # use_lockfile activa el bloqueo nativo de S3 (Terraform 1.10+). Antes hacía
  # falta una tabla de DynamoDB solo para esto: un recurso menos que crear,
  # explicar y pagar.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      ManagedBy = "terraform"
      Owner     = var.owner
    }
  }
}

data "aws_caller_identity" "actual" {}

locals {
  # Prefijo común de todos los recursos: caudalit-esios-dev-...
  prefijo = "${var.project}-${var.env}"

  # Los nombres de bucket son únicos a nivel mundial. El ID de cuenta se
  # obtiene en tiempo de ejecución, no se escribe en el repositorio.
  sufijo = data.aws_caller_identity.actual.account_id
}
