resource "aws_kinesis_stream" "lifecycle" {
  name             = "${local.name}-payment-lifecycle"
  shard_count      = var.kinesis_shard_count
  retention_period = 72
  encryption_type  = "KMS"
  kms_key_id       = aws_kms_key.data.arn

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

resource "aws_sqs_queue" "identity_dlq" {
  name                              = "${local.name}-identity-gate-dlq"
  kms_master_key_id                 = aws_kms_key.data.arn
  message_retention_seconds         = 1209600
  kms_data_key_reuse_period_seconds = 300
}

resource "aws_dynamodb_table" "event_identity" {
  name         = "${local.name}-event-identity"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
}

resource "aws_lambda_function" "identity_gate" {
  function_name = "${local.name}-schema-identity-gate"
  package_type  = "Image"
  image_uri     = var.identity_gate_image_uri
  role          = aws_iam_role.identity_gate.arn
  timeout       = 60
  memory_size   = 1024

  environment {
    variables = {
      BRONZE_BUCKET        = aws_s3_bucket.data["bronze"].id
      ACCEPTED_BUCKET      = aws_s3_bucket.data["accepted"].id
      QUARANTINE_BUCKET    = aws_s3_bucket.data["quarantine"].id
      IDENTITY_TABLE       = aws_dynamodb_table.event_identity.name
      TOKEN_SECRET_ARN     = aws_secretsmanager_secret.token_key.arn
      KMS_KEY_ARN          = aws_kms_key.data.arn
      SOURCE_REGISTRY_PATH = "/var/task/config/sources.json"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_event_source_mapping" "lifecycle" {
  event_source_arn                   = aws_kinesis_stream.lifecycle.arn
  function_name                      = aws_lambda_function.identity_gate.arn
  starting_position                  = "TRIM_HORIZON"
  batch_size                         = 500
  maximum_batching_window_in_seconds = 5
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 5
  parallelization_factor             = 2
  function_response_types            = ["ReportBatchItemFailures"]

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.identity_dlq.arn
    }
  }
}
