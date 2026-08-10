terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

check "digest_pinned_lambda_images" {
  assert {
    condition = alltrue([
      can(regex("@sha256:[a-f0-9]{64}$", var.identity_gate_image_uri)),
      can(regex("@sha256:[a-f0-9]{64}$", var.manifest_loader_image_uri))
    ])
    error_message = "Lambda image URIs must be pinned to immutable sha256 digests."
  }
}

check "cdc_inputs" {
  assert {
    condition = !var.enable_cdc || (
      var.vpc_id != null && length(var.private_subnet_ids) >= 2 &&
      var.cdc_source_endpoint_arn != null && var.cdc_source_security_group_id != null
    )
    error_message = "CDC requires a VPC, two private subnets, a source endpoint and source security group."
  }
}

check "redshift_inputs" {
  assert {
    condition     = !var.enable_redshift || (var.vpc_id != null && length(var.private_subnet_ids) >= 3)
    error_message = "Redshift Serverless requires a VPC and at least three private subnets."
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name = "${var.project_name}-${var.environment}"
  tags = {
    Application        = var.project_name
    Environment        = var.environment
    ManagedBy          = "terraform"
    DataClassification = "financial-confidential"
  }
  database = replace(local.name, "-", "_")
  catalog  = "glue_catalog"
  tables = {
    accepted_event       = "${local.catalog}.${local.database}.accepted_event"
    payment_state        = "${local.catalog}.${local.database}.payment_state"
    business_exception   = "${local.catalog}.${local.database}.business_exception"
    posted_event         = "${local.catalog}.${local.database}.posted_event"
    ledger_entry         = "${local.catalog}.${local.database}.ledger_entry"
    settlement_evidence  = "${local.catalog}.${local.database}.settlement_evidence"
    settlement_exception = "${local.catalog}.${local.database}.settlement_exception"
  }
}
