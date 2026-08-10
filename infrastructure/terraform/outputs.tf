output "bronze_bucket" {
  value = aws_s3_bucket.data["bronze"].id
}

output "accepted_bucket" {
  value = aws_s3_bucket.data["accepted"].id
}

output "verified_settlement_bucket" {
  value = aws_s3_bucket.data["verified"].id
}

output "settlement_publication_table" {
  value = aws_dynamodb_table.settlement_publication.name
}

output "settlement_state_machine_arn" {
  value = aws_sfn_state_machine.settlement.arn
}

output "lifecycle_stream_arn" {
  value = aws_kinesis_stream.lifecycle.arn
}

output "glue_database" {
  value = aws_glue_catalog_database.ledgerflow.name
}

output "bootstrap_job_name" {
  value = aws_glue_job.job["bootstrap_tables"].name
}

output "bootstrap_ddl_uri" {
  value = "s3://${aws_s3_object.iceberg_ddl.bucket}/${aws_s3_object.iceberg_ddl.key}"
}

output "token_secret_arn" {
  value = aws_secretsmanager_secret.token_key.arn
}

output "redshift_spectrum_role_arn" {
  value = var.enable_redshift ? aws_iam_role.redshift_spectrum[0].arn : null
}

output "redshift_workgroup_endpoint" {
  value       = var.enable_redshift ? aws_redshiftserverless_workgroup.finance[0].endpoint[0].address : null
  description = "Null when the optional serving layer is disabled."
}
