resource "aws_s3_bucket" "data" {
  for_each = toset(["bronze", "accepted", "quarantine", "control", "verified", "warehouse", "artifacts"])

  bucket_prefix       = "${local.name}-${each.key}-"
  force_destroy       = false
  object_lock_enabled = each.key == "bronze"
}

resource "aws_s3_bucket_public_access_block" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.data.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_object_lock_configuration" "bronze" {
  bucket = aws_s3_bucket.data["bronze"].id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.environment == "prod" ? 2555 : 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.data["bronze"]]
}

resource "aws_s3_bucket_lifecycle_configuration" "noncurrent" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    id     = "noncurrent-retention"
    status = "Enabled"
    noncurrent_version_expiration {
      noncurrent_days = var.environment == "prod" ? 365 : 30
    }
  }
}

resource "aws_s3_bucket_notification" "bronze_eventbridge" {
  bucket      = aws_s3_bucket.data["bronze"].id
  eventbridge = true
}

data "aws_iam_policy_document" "data_bucket" {
  for_each = aws_s3_bucket.data

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "control" ? [1] : []
    content {
      sid       = "CloudTrailBucketAcl"
      actions   = ["s3:GetBucketAcl"]
      resources = [each.value.arn]
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

  dynamic "statement" {
    for_each = each.key == "control" ? [1] : []
    content {
      sid       = "CloudTrailWrite"
      actions   = ["s3:PutObject"]
      resources = ["${each.value.arn}/cloudtrail/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
      principals {
        type        = "Service"
        identifiers = ["cloudtrail.amazonaws.com"]
      }
      condition {
        test     = "StringEquals"
        variable = "s3:x-amz-acl"
        values   = ["bucket-owner-full-control"]
      }
      condition {
        test     = "StringEquals"
        variable = "aws:SourceArn"
        values   = ["arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${local.name}-data-access"]
      }
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  policy   = data.aws_iam_policy_document.data_bucket[each.key].json
}

resource "aws_cloudtrail" "data_access" {
  name                          = "${local.name}-data-access"
  s3_bucket_name                = aws_s3_bucket.data["control"].id
  s3_key_prefix                 = "cloudtrail"
  kms_key_id                    = aws_kms_key.data.arn
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  event_selector {
    read_write_type           = "All"
    include_management_events = true
    data_resource {
      type = "AWS::S3::Object"
      values = [
        "${aws_s3_bucket.data["bronze"].arn}/",
        "${aws_s3_bucket.data["accepted"].arn}/",
        "${aws_s3_bucket.data["quarantine"].arn}/",
        "${aws_s3_bucket.data["verified"].arn}/",
        "${aws_s3_bucket.data["warehouse"].arn}/"
      ]
    }
  }

  depends_on = [aws_s3_bucket_policy.data]
}
