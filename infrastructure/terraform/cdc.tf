resource "aws_security_group" "dms" {
  count = var.enable_cdc ? 1 : 0

  name_prefix = "${local.name}-dms-"
  description = "Egress for DMS outbox replication"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "AWS APIs through NAT or VPC endpoints"
  }

  egress {
    from_port       = var.cdc_source_port
    to_port         = var.cdc_source_port
    protocol        = "tcp"
    security_groups = var.cdc_source_security_group_id == null ? [] : [var.cdc_source_security_group_id]
    description     = "Approved payment-outbox source"
  }
}

resource "aws_dms_replication_subnet_group" "cdc" {
  count = var.enable_cdc ? 1 : 0

  replication_subnet_group_id          = "${local.name}-cdc"
  replication_subnet_group_description = "Private subnets for LedgerFlow CDC"
  subnet_ids                           = var.private_subnet_ids
}

resource "aws_dms_replication_instance" "cdc" {
  count = var.enable_cdc ? 1 : 0

  replication_instance_id     = "${local.name}-cdc"
  replication_instance_class  = "dms.t3.medium"
  allocated_storage           = 100
  auto_minor_version_upgrade  = true
  publicly_accessible         = false
  multi_az                    = var.environment == "prod"
  replication_subnet_group_id = aws_dms_replication_subnet_group.cdc[0].id
  vpc_security_group_ids      = [aws_security_group.dms[0].id]
  kms_key_arn                 = aws_kms_key.data.arn
}

resource "aws_dms_endpoint" "kinesis" {
  count = var.enable_cdc ? 1 : 0

  endpoint_id   = "${local.name}-kinesis-target"
  endpoint_type = "target"
  engine_name   = "kinesis"

  kinesis_settings {
    stream_arn              = aws_kinesis_stream.lifecycle.arn
    service_access_role_arn = aws_iam_role.dms_kinesis[0].arn
    message_format          = "json"
  }
}

resource "aws_dms_replication_task" "outbox" {
  count = var.enable_cdc ? 1 : 0

  replication_task_id      = "${local.name}-payment-outbox"
  migration_type           = "cdc"
  replication_instance_arn = aws_dms_replication_instance.cdc[0].replication_instance_arn
  source_endpoint_arn      = var.cdc_source_endpoint_arn
  target_endpoint_arn      = aws_dms_endpoint.kinesis[0].endpoint_arn
  table_mappings = jsonencode({
    rules = [{
      "rule-type"      = "selection"
      "rule-id"        = "1"
      "rule-name"      = "payment-outbox"
      "object-locator" = { "schema-name" = "%", "table-name" = "payment_outbox" }
      "rule-action"    = "include"
    }]
  })
}
