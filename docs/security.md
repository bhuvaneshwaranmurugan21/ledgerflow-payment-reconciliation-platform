# Security boundary

- Raw financial evidence uses a dedicated KMS key, S3 Object Lock and restricted IAM roles.
- TLS-only bucket policies reject insecure transport.
- PAN, CVV, PIN and track data are rejected recursively before raw persistence; operational
  quarantine retains only a redacted representation.
- Curated customer identity uses keyed HMAC-SHA-256; the key is obtained from Secrets Manager.
- Quarantine payloads redact email and prohibited fields before operational presentation.
- Lake Formation separates raw, ledger, audit and finance-consumer permissions.
- CloudTrail and CloudWatch retain access and reconciliation evidence.
- Redshift credentials are managed through Secrets Manager; no production profile is committed.

The local development token key is explicitly synthetic and must never be deployed.

Terraform creates the Secrets Manager container but never receives the HMAC value, so the key is
not written into Terraform state. The secret-aware deployment environment injects it directly into
Secrets Manager. Lambda image variables require immutable image digests. CloudTrail data events
cover bronze, accepted, verified-settlement and warehouse objects; bucket policies deny non-TLS
access. Settlement processing is bound to the source S3 version that passed checksum validation,
then copied server-side into a separately writable verified-input boundary.
