resource "aws_lambda_function" "manifest_loader" {
  function_name = "${local.name}-manifest-loader"
  package_type  = "Image"
  image_uri     = var.manifest_loader_image_uri
  role          = aws_iam_role.manifest_loader.arn
  timeout       = 60
  memory_size   = 512

  environment {
    variables = {
      SETTLEMENT_STATE_MACHINE_ARN = aws_sfn_state_machine.settlement.arn
      SETTLEMENT_PUBLICATION_TABLE = aws_dynamodb_table.settlement_publication.name
      VERIFIED_SETTLEMENT_BUCKET   = aws_s3_bucket.data["verified"].id
      KMS_KEY_ARN                  = aws_kms_key.data.arn
    }
  }


  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_dynamodb_table" "settlement_publication" {
  name         = "${local.name}-settlement-publication"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "business_date"

  attribute {
    name = "business_date"
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

resource "aws_cloudwatch_event_rule" "settlement_manifest" {
  name = "${local.name}-settlement-manifest"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.data["bronze"].id] }
      object = { key = [{ wildcard = "settlements/*.manifest.json" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "manifest_loader" {
  rule = aws_cloudwatch_event_rule.settlement_manifest.name
  arn  = aws_lambda_function.manifest_loader.arn
}

resource "aws_lambda_permission" "eventbridge_manifest" {
  statement_id  = "AllowEventBridgeSettlementManifest"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.manifest_loader.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.settlement_manifest.arn
}
