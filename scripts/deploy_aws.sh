#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 path/to/environment.tfvars" >&2
  exit 2
fi

if [[ -z "${LEDGERFLOW_TOKEN_KEY:-}" || ${#LEDGERFLOW_TOKEN_KEY} -lt 32 ]]; then
  echo "LEDGERFLOW_TOKEN_KEY must come from the secret-aware deployment environment" >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
terraform_dir="${project_root}/infrastructure/terraform"
tfvars_file="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"

terraform -chdir="${terraform_dir}" init
terraform -chdir="${terraform_dir}" fmt -check
terraform -chdir="${terraform_dir}" validate
terraform -chdir="${terraform_dir}" plan -var-file="${tfvars_file}" -out=ledgerflow.tfplan
terraform -chdir="${terraform_dir}" apply ledgerflow.tfplan

database="$(terraform -chdir="${terraform_dir}" output -raw glue_database)"
bootstrap_job="$(terraform -chdir="${terraform_dir}" output -raw bootstrap_job_name)"
bootstrap_ddl_uri="$(terraform -chdir="${terraform_dir}" output -raw bootstrap_ddl_uri)"
token_secret_arn="$(terraform -chdir="${terraform_dir}" output -raw token_secret_arn)"
printf '%s' "${LEDGERFLOW_TOKEN_KEY}" | aws secretsmanager put-secret-value \
  --secret-id "${token_secret_arn}" --secret-string file:///dev/stdin >/dev/null
run_id="$(aws glue start-job-run --job-name "${bootstrap_job}" \
  --arguments "--database=${database},--ddl-path=${bootstrap_ddl_uri}" \
  --query JobRunId --output text)"

while true; do
  state="$(aws glue get-job-run --job-name "${bootstrap_job}" --run-id "${run_id}" \
    --query JobRun.JobRunState --output text)"
  case "${state}" in
    SUCCEEDED) break ;;
    FAILED|ERROR|TIMEOUT|STOPPED) echo "bootstrap failed: ${state}" >&2; exit 1 ;;
    *) sleep 15 ;;
  esac
done

echo "LedgerFlow infrastructure and Iceberg catalog bootstrap succeeded."
