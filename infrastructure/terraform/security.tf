resource "aws_kms_key" "data" {
  description             = "LedgerFlow financial data key"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  multi_region            = var.environment == "prod"
  policy                  = data.aws_iam_policy_document.data_key.json
}

data "aws_iam_policy_document" "data_key" {
  statement {
    sid       = "EnableAccountIAM"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
  statement {
    sid = "AllowCloudWatchLogsEncryption"
    actions = [
      "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
  statement {
    sid       = "AllowCloudWatchAlarmToEncryptedSNS"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com", "sns.amazonaws.com"]
    }
  }
  statement {
    sid       = "AllowCloudTrailEncryption"
    actions   = ["kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${local.name}-data-access"]
    }
  }
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_secretsmanager_secret" "token_key" {
  name                    = "${local.name}/identity-hmac-key"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "identity_gate" {
  name               = "${local.name}-identity-gate"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "identity_gate" {
  statement {
    sid = "ReadLifecycleStream"
    actions = [
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:ListShards",
      "kinesis:SubscribeToShard"
    ]
    resources = [aws_kinesis_stream.lifecycle.arn]
  }
  statement {
    sid     = "WriteClassifiedObjects"
    actions = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [
      "${aws_s3_bucket.data["bronze"].arn}/*",
      "${aws_s3_bucket.data["accepted"].arn}/*",
      "${aws_s3_bucket.data["quarantine"].arn}/*"
    ]
  }
  statement {
    sid       = "IdentityConditionalWrite"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.event_identity.arn]
  }
  statement {
    sid       = "ReadTokenSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.token_key.arn]
  }
  statement {
    sid       = "EncryptData"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "SendFailedBatch"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.identity_dlq.arn]
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name}-schema-identity-gate:*"]
  }
}

resource "aws_iam_role_policy" "identity_gate" {
  role   = aws_iam_role.identity_gate.id
  policy = data.aws_iam_policy_document.identity_gate.json
}

resource "aws_iam_role" "manifest_loader" {
  name               = "${local.name}-manifest-loader"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "manifest_loader" {
  statement {
    sid       = "ReadSettlementEvidence"
    actions   = ["s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectAttributes", "s3:ListBucket"]
    resources = [aws_s3_bucket.data["bronze"].arn, "${aws_s3_bucket.data["bronze"].arn}/settlements/*"]
  }
  statement {
    sid       = "WriteVerifiedSettlement"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data["verified"].arn}/settlements/*"]
  }
  statement {
    sid       = "RegisterSettlementRevision"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.settlement_publication.arn]
  }
  statement {
    sid       = "StartOwnedWorkflow"
    actions   = ["states:StartExecution"]
    resources = ["arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.name}-settlement"]
  }
  statement {
    sid       = "DecryptData"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name}-manifest-loader:*"]
  }
}

resource "aws_iam_role_policy" "manifest_loader" {
  role   = aws_iam_role.manifest_loader.id
  policy = data.aws_iam_policy_document.manifest_loader.json
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue" {
  name               = "${local.name}-glue"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
}

data "aws_iam_policy_document" "glue" {
  statement {
    sid       = "ProjectData"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = flatten([for bucket in aws_s3_bucket.data : [bucket.arn, "${bucket.arn}/*"]])
  }
  statement {
    sid = "GlueCatalog"
    actions = [
      "glue:CreateDatabase", "glue:GetDatabase", "glue:GetDatabases", "glue:CreateTable",
      "glue:UpdateTable", "glue:GetTable", "glue:GetTables", "glue:GetPartitions",
      "glue:CreatePartition", "glue:BatchCreatePartition", "glue:UpdatePartition",
      "glue:DeletePartition"
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${local.database}",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.database}/*"
    ]
  }
  statement {
    sid       = "DataKey"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "LogsAndMetrics"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "cloudwatch:PutMetricData"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "glue" {
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue.json
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "states" {
  name               = "${local.name}-settlement-workflow"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "states" {
  statement {
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
    resources = ["arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job/${local.name}-*"]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data["control"].arn}/gates/*"]
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.settlement_publication.arn]
  }
  statement {
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForGlueJobRunsRule"]
  }
}

resource "aws_iam_role_policy" "states" {
  role   = aws_iam_role.states.id
  policy = data.aws_iam_policy_document.states.json
}

data "aws_iam_policy_document" "dms_assume" {
  count = var.enable_cdc ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["dms.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dms_kinesis" {
  count = var.enable_cdc ? 1 : 0

  name               = "${local.name}-dms-kinesis"
  assume_role_policy = data.aws_iam_policy_document.dms_assume[0].json
}

resource "aws_iam_role_policy" "dms_kinesis" {
  count = var.enable_cdc ? 1 : 0
  role  = aws_iam_role.dms_kinesis[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kinesis:DescribeStream", "kinesis:PutRecord", "kinesis:PutRecords"]
      Resource = aws_kinesis_stream.lifecycle.arn
    }]
  })
}

resource "aws_lakeformation_resource" "warehouse" {
  arn                     = aws_s3_bucket.data["warehouse"].arn
  role_arn                = aws_iam_role.glue.arn
  use_service_linked_role = false
}

resource "aws_lakeformation_permissions" "glue_database" {
  principal   = aws_iam_role.glue.arn
  permissions = ["ALL"]
  database {
    name = aws_glue_catalog_database.ledgerflow.name
  }
}

resource "aws_lakeformation_permissions" "glue_tables" {
  principal   = aws_iam_role.glue.arn
  permissions = ["ALL"]
  table {
    database_name = aws_glue_catalog_database.ledgerflow.name
    wildcard      = true
  }
}

data "aws_iam_policy_document" "redshift_assume" {
  count = var.enable_redshift ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["redshift.amazonaws.com", "redshift-serverless.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "redshift_spectrum" {
  count = var.enable_redshift ? 1 : 0

  name               = "${local.name}-redshift-spectrum"
  assume_role_policy = data.aws_iam_policy_document.redshift_assume[0].json
}

resource "aws_iam_role_policy" "redshift_spectrum" {
  count = var.enable_redshift ? 1 : 0
  role  = aws_iam_role.redshift_spectrum[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${local.database}",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.database}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.data["warehouse"].arn, "${aws_s3_bucket.data["warehouse"].arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.data.arn]
      }
    ]
  })
}

resource "aws_lakeformation_permissions" "redshift_tables" {
  count = var.enable_redshift ? 1 : 0

  principal   = aws_iam_role.redshift_spectrum[0].arn
  permissions = ["DESCRIBE", "SELECT"]
  table {
    database_name = aws_glue_catalog_database.ledgerflow.name
    wildcard      = true
  }
}
