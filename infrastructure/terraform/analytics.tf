resource "aws_athena_workgroup" "audit" {
  name = "${local.name}-audit"
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 107374182400
    result_configuration {
      output_location = "s3://${aws_s3_bucket.data["control"].id}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.data.arn
      }
    }
  }
}

resource "aws_security_group" "redshift" {
  count = var.enable_redshift ? 1 : 0

  name_prefix = "${local.name}-redshift-"
  description = "Private Redshift Serverless finance endpoint"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_redshiftserverless_namespace" "finance" {
  count = var.enable_redshift ? 1 : 0

  namespace_name        = "${local.name}-finance"
  db_name               = "finance"
  admin_username        = var.redshift_admin_username
  manage_admin_password = true
  kms_key_id            = aws_kms_key.data.arn
  log_exports           = ["userlog", "connectionlog", "useractivitylog"]
  iam_roles             = [aws_iam_role.redshift_spectrum[0].arn]
}

resource "aws_redshiftserverless_workgroup" "finance" {
  count = var.enable_redshift ? 1 : 0

  workgroup_name      = "${local.name}-finance"
  namespace_name      = aws_redshiftserverless_namespace.finance[0].namespace_name
  base_capacity       = 32
  publicly_accessible = false
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.redshift[0].id]

  config_parameter {
    parameter_key   = "enable_user_activity_logging"
    parameter_value = "true"
  }
}

resource "aws_redshiftserverless_usage_limit" "monthly" {
  count = var.enable_redshift ? 1 : 0

  resource_arn  = aws_redshiftserverless_workgroup.finance[0].arn
  usage_type    = "RPU_TIME"
  amount        = 2000
  period        = "MONTHLY"
  breach_action = "log"
}
