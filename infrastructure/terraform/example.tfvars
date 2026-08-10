aws_region                = "ap-south-1"
environment               = "dev"
identity_gate_image_uri   = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/ledgerflow-identity@sha256:replace"
manifest_loader_image_uri = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/ledgerflow-manifest@sha256:replace"

# Optional serving layer. Requires a VPC and three private subnets.
enable_redshift    = false
vpc_id             = null
private_subnet_ids = []

# Optional legacy payment_outbox CDC. Supply an existing encrypted source endpoint.
enable_cdc                   = false
cdc_source_endpoint_arn      = null
cdc_source_security_group_id = null
