#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 AWS_ACCOUNT_ID AWS_REGION" >&2
  exit 2
fi

account_id="$1"
aws_region="$2"
registry="${account_id}.dkr.ecr.${aws_region}.amazonaws.com"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

aws ecr get-login-password --region "${aws_region}" | \
  docker login --username AWS --password-stdin "${registry}"

for component in identity-gate manifest-loader; do
  repository="ledgerflow-${component}"
  aws ecr describe-repositories --repository-names "${repository}" --region "${aws_region}" \
    >/dev/null 2>&1 || aws ecr create-repository --repository-name "${repository}" \
    --image-scanning-configuration scanOnPush=true --image-tag-mutability IMMUTABLE \
    --region "${aws_region}" >/dev/null
  image="${registry}/${repository}:$(git -C "${project_root}" rev-parse --short=12 HEAD)"
  docker build --provenance=true --sbom=true \
    -f "${project_root}/containers/${component}.Dockerfile" -t "${image}" "${project_root}"
  docker push "${image}"
  digest="$(aws ecr describe-images --repository-name "${repository}" --region "${aws_region}" \
    --image-ids imageTag="${image##*:}" --query 'imageDetails[0].imageDigest' --output text)"
  echo "${component}=${registry}/${repository}@${digest}"
done
