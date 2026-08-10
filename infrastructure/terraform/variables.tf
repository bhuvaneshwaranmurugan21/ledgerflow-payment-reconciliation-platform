variable "aws_region" {
  description = "AWS region for the platform."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Stable lowercase platform identifier."
  type        = string
  default     = "ledgerflow"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.project_name))
    error_message = "project_name must be a lowercase DNS-compatible identifier."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "environment must be dev, stage or prod."
  }
}

variable "identity_gate_image_uri" {
  description = "Immutable ECR image URI (preferably digest-pinned) for the identity gate."
  type        = string
}

variable "manifest_loader_image_uri" {
  description = "Immutable ECR image URI (preferably digest-pinned) for the manifest loader."
  type        = string
}

variable "kinesis_shard_count" {
  description = "Modeled starting shard count; tune from observed throughput and hot keys."
  type        = number
  default     = 4
  validation {
    condition     = var.kinesis_shard_count >= 1
    error_message = "kinesis_shard_count must be positive."
  }
}

variable "glue_worker_type" {
  type    = string
  default = "G.2X"
}

variable "glue_worker_count" {
  type    = number
  default = 10
}

variable "alert_email" {
  description = "Optional subscription endpoint; confirmation remains manual."
  type        = string
  default     = null
}

variable "vpc_id" {
  description = "VPC used only when CDC or Redshift Serverless is enabled."
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "At least two private subnets for CDC; at least three for Redshift Serverless."
  type        = list(string)
  default     = []
}

variable "enable_cdc" {
  type    = bool
  default = false
}

variable "cdc_source_endpoint_arn" {
  description = "Existing encrypted DMS source endpoint for an outbox-shaped payments database."
  type        = string
  default     = null
}

variable "cdc_source_security_group_id" {
  description = "Security group attached to the existing CDC source database."
  type        = string
  default     = null
}

variable "cdc_source_port" {
  type    = number
  default = 5432
}

variable "enable_redshift" {
  type    = bool
  default = false
}

variable "redshift_admin_username" {
  type    = string
  default = "ledgerflow_admin"
}
