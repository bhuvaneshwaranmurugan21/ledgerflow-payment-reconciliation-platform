resource "aws_glue_catalog_database" "ledgerflow" {
  name        = local.database
  description = "LedgerFlow Iceberg catalog"
}

locals {
  glue_scripts = {
    bootstrap_tables             = "spark_jobs/bootstrap_tables.py"
    validate_settlement_manifest = "spark_jobs/validate_settlement_manifest.py"
    ingest_accepted_events       = "spark_jobs/ingest_accepted_events.py"
    reconstruct_payment_state    = "spark_jobs/reconstruct_payment_state.py"
    post_ledger                  = "spark_jobs/post_ledger.py"
    reconcile_settlements        = "spark_jobs/reconcile_settlements.py"
    maintain_iceberg             = "spark_jobs/maintain_iceberg.py"
  }
}

resource "aws_s3_object" "glue_script" {
  for_each = local.glue_scripts

  bucket                 = aws_s3_bucket.data["artifacts"].id
  key                    = "glue/${each.key}.py"
  source                 = "${path.module}/../../${each.value}"
  etag                   = filemd5("${path.module}/../../${each.value}")
  server_side_encryption = "aws:kms"
  kms_key_id             = aws_kms_key.data.arn
}

resource "aws_s3_object" "iceberg_ddl" {
  bucket                 = aws_s3_bucket.data["artifacts"].id
  key                    = "glue/create_iceberg_tables.sql"
  source                 = "${path.module}/../sql/create_iceberg_tables.sql"
  etag                   = filemd5("${path.module}/../sql/create_iceberg_tables.sql")
  server_side_encryption = "aws:kms"
  kms_key_id             = aws_kms_key.data.arn
}

resource "aws_glue_job" "job" {
  for_each = local.glue_scripts

  name              = "${local.name}-${replace(each.key, "_", "-")}"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = var.glue_worker_type
  number_of_workers = var.glue_worker_count
  max_retries       = 0
  timeout           = 60
  execution_class   = "STANDARD"
  max_capacity      = null

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_object.glue_script[each.key].bucket}/${aws_s3_object.glue_script[each.key].key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-glue-datacatalog"          = "true"
    "--datalake-formats"                 = "iceberg"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--conf" = join(" ", [
      "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
      "spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog",
      "spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog",
      "spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO",
      "spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.data["warehouse"].id}/"
    ])
  }
}
