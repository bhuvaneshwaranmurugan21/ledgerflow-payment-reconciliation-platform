-- Run once through the Redshift Data API after the optional Serverless workgroup is active.
-- Replace the placeholders from Terraform outputs; the role is scoped to this Glue database.
CREATE EXTERNAL SCHEMA IF NOT EXISTS REPLACE_WITH_EXTERNAL_SCHEMA
FROM DATA CATALOG
DATABASE 'REPLACE_WITH_GLUE_DATABASE'
IAM_ROLE 'REPLACE_WITH_REDSHIFT_SPECTRUM_ROLE_ARN'
CREATE EXTERNAL DATABASE IF NOT EXISTS;

CREATE SCHEMA IF NOT EXISTS ledgerflow_staging;
CREATE SCHEMA IF NOT EXISTS ledgerflow_finance;
