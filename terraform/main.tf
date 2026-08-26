terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Configuracion parcial: el bucket real va en backend.hcl, que no se versiona.
  #   terraform init -backend-config=backend.hcl
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
  prefijo = "${var.project}-${var.env}"

  # En tiempo de ejecucion: el repositorio es publico.
  sufijo = data.aws_caller_identity.actual.account_id
}
