resource "aws_cloudwatch_log_group" "settlement_workflow" {
  name              = "/aws/vendedlogs/states/${local.name}-settlement"
  retention_in_days = var.environment == "prod" ? 365 : 30
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_sfn_state_machine" "settlement" {
  name     = "${local.name}-settlement"
  role_arn = aws_iam_role.states.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/../../orchestration/stepfunctions/settlement_workflow.asl.json", {
    manifest_validation_job      = aws_glue_job.job["validate_settlement_manifest"].name
    accepted_ingestion_job       = aws_glue_job.job["ingest_accepted_events"].name
    payment_state_job            = aws_glue_job.job["reconstruct_payment_state"].name
    ledger_job                   = aws_glue_job.job["post_ledger"].name
    reconciliation_job           = aws_glue_job.job["reconcile_settlements"].name
    accepted_bucket              = aws_s3_bucket.data["accepted"].id
    accepted_event_table         = local.tables.accepted_event
    payment_state_table          = local.tables.payment_state
    business_exception_table     = local.tables.business_exception
    posted_event_table           = local.tables.posted_event
    ledger_table                 = local.tables.ledger_entry
    settlement_evidence_table    = local.tables.settlement_evidence
    settlement_exception_table   = local.tables.settlement_exception
    settlement_publication_table = aws_dynamodb_table.settlement_publication.name
    control_bucket               = aws_s3_bucket.data["control"].id
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.settlement_workflow.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }
}

resource "aws_s3_object" "airflow_dag" {
  bucket                 = aws_s3_bucket.data["artifacts"].id
  key                    = "airflow/dags/ledgerflow_finance_dag.py"
  source                 = "${path.module}/../../orchestration/airflow/ledgerflow_finance_dag.py"
  etag                   = filemd5("${path.module}/../../orchestration/airflow/ledgerflow_finance_dag.py")
  server_side_encryption = "aws:kms"
  kms_key_id             = aws_kms_key.data.arn
}

resource "aws_s3_object" "airflow_maintenance_dag" {
  bucket                 = aws_s3_bucket.data["artifacts"].id
  key                    = "airflow/dags/ledgerflow_maintenance_dag.py"
  source                 = "${path.module}/../../orchestration/airflow/ledgerflow_maintenance_dag.py"
  etag                   = filemd5("${path.module}/../../orchestration/airflow/ledgerflow_maintenance_dag.py")
  server_side_encryption = "aws:kms"
  kms_key_id             = aws_kms_key.data.arn
}
