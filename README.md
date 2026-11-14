# Blast-Radius Guard — AWS SRE & Kubernetes Progressive Delivery Platform

**Blast-Radius Guard** is an event-driven configuration validation and cellular Kubernetes progressive delivery platform built entirely with **POSIX Bash, Terraform, Docker, Kubernetes (Amazon EKS & Kind), Prometheus, and AWS DevSecOps services**.

It prevents defective or unverified configuration changes from causing cascading outages by enforcing cryptographic and schema gates before deployment, shifting serverless validator traffic via **AWS CodeDeploy Canary (`LambdaCanary10Percent5Minutes`)**, and promoting configuration updates cell-by-cell (`blast-cell-1` → `blast-cell-2` → `blast-cell-3`) with automated **Site Reliability Engineering (SRE) SLI/SLO error budget checks** and cryptographic **Last-Known-Good (LKG) rollback**.

---

## Architecture Overview

1. **Source & CI/CD Orchestration (`GitHub Actions`, `AWS CodePipeline`, `AWS CodeBuild`, `Amazon ECR`):**
   * Lints all Bash scripts (`bash -n`), runs candidate YAML validation and Ed25519 signature checks, emits JUnit XML test reports, builds the non-root (`USER 10001`) Alpine/Bash consumer container image, and pushes it to **Amazon ECR**.
2. **Serverless Validation & Canary Delivery (`Amazon S3`, `Amazon EventBridge`, `AWS Lambda`, `Amazon API Gateway`, `AWS CodeDeploy`):**
   * Versioned **Amazon S3** configuration store emits `Object Created` events for prefix `blast-radius-guard/configs/` to **Amazon EventBridge**.
   * **AWS Lambda** (`provided.al2023` custom Bash runtime via `lambda/bootstrap`) validates payload size (≤ 1 MiB), required schema keys, and SHA-256 digests.
   * **Amazon API Gateway (HTTP API)** exposes an `AWS_IAM` SigV4-authenticated `POST /validate` endpoint backed by the Lambda `live` alias.
   * **AWS CodeDeploy** shifts traffic between Lambda versions using `CodeDeployDefault.LambdaCanary10Percent5Minutes` and automatically rolls back when the **Amazon CloudWatch** alarm (`blast-radius-lambda-errors`) breaches threshold.
3. **Cellular Kubernetes Rollout & Auto-Remediation (`Amazon EKS` / `Kind`, `Prometheus`):**
   * `scripts/rollout_guard.sh` orchestrates a 7-state rollout machine across three isolated Kubernetes deployment cells (`blast-cell-1`, `blast-cell-2`, `blast-cell-3` representing logical blast-radius stages).
   * During each cell's bake window, the controller queries **Prometheus** SLIs (`http_requests_total` and `config_reload_errors_total`) against a 99.9% availability SLO. If readiness probes fail, runtime failure is injected (`INJECT_RUNTIME_FAILURE: true`), or reload errors exceed 0, the controller halts promotion and restores SHA-256 verified LKG `ConfigMap` backups.
4. **Immutable SRE Audit Trail (`Amazon DynamoDB`, `AWS Glue Data Catalog`, `Amazon S3`):**
   * Every state transition records the rollout ID, candidate artifact, SHA-256 hash, state, and remaining SLO error budget percentage to **Amazon DynamoDB** (`blast-radius-rollout-audit`) and structured JSON logs in **Amazon S3** cataloged by **AWS Glue** (`blast_radius_audit_db.rollout_events`).

---

## Pure Bash Engineering Stack (Zero Python Runtime)

| Component | Path | Technology & Tooling |
| :--- | :--- | :--- |
| **Pre-Deploy Validator** | `scripts/validate_config.sh` | Bash, `yq`, `jq`, `sha256sum`, `openssl pkeyutl` (Ed25519 signature verification) |
| **Rollout Controller** | `scripts/rollout_guard.sh` | Bash, `kubectl`, `curl`, `jq`, `aws s3`, `aws dynamodb` |
| **Config Consumer Service** | `consumer/server.sh` | Alpine Linux (`USER 10001`), Bash, `socat`, `yq`, `jq` serving `/healthz`, `/readyz`, `/metrics` |
| **Lambda Validator** | `lambda/bootstrap` | AWS Lambda Custom Runtime (`provided.al2023`), Bash, `curl`, `jq`, `sha256sum` |
| **Infrastructure as Code** | `terraform/*.tf` | Terraform provisioning VPC (Zero-NAT + S3 Gateway Endpoint), S3, IAM, Lambda, API GW, EventBridge, ECR, CodeBuild, CodeDeploy, CodePipeline, DynamoDB, Glue |

---

## Progressive Delivery State Machine & SRE Error Budget Model

The controller (`scripts/rollout_guard.sh`) transitions strictly through the following states:

```text
PENDING → VALIDATING → PROMOTING → BAKING
                              ├── HEALTHY (if E_reload = 0 across all 3 cells)
                              └── ROLLING_BACK → HALTED (if probe fails or E_reload > 0)
```

### Service Level Indicators (SLIs) & Service Level Objectives (SLOs)

Each cell exposes Prometheus metrics on `:8000/metrics`:

* `http_requests_total{cell="blast-cell-N"}`: Total HTTP requests processed by the cell.
* `config_reload_errors_total{cell="blast-cell-N"}`: Active schema or runtime configuration errors.
* `slo_target_ratio{cell="blast-cell-N"}`: Target availability ratio (`0.999` or `99.9%`).

The availability SLI over a rollout bake window is defined as:

```text
SLI_availability = (R_total - E_reload) / R_total
```

When `E_reload >= 1` or a deterministic failure (`INJECT_RUNTIME_FAILURE: true`) is detected during the bake window, the remaining rollout error budget drops to `0.0%`, triggering immediate auto-remediation across all cells.

---

## Repository Structure

```text
.
├── .github/workflows/
│   └── ci.yml                       # Pure Bash DevSecOps & container smoke-test CI workflow
├── config/                          # Candidate YAML configs (valid, v1.4 + Ed25519 .sig, broken, oversized, failure)
├── consumer/
│   ├── Dockerfile                   # Non-root (USER 10001) Alpine + Bash/socat/jq/yq container image
│   ├── rules.yaml                   # Default baseline rules mounted at /app/rules.yaml
│   ├── schema/rules.schema.json     # Configuration schema contract
│   └── server.sh                    # Pure Bash HTTP & Prometheus SLI/SLO metrics server
├── deploy/
│   ├── cells/                       # Kubernetes manifests for blast-cell-1, blast-cell-2, blast-cell-3 & Services
│   └── monitoring/                  # Prometheus deployment & scrape configuration
├── evidence/                        # Dated verification logs & JSON outputs from live AWS execution
├── lambda/
│   └── bootstrap                    # AWS Lambda custom runtime (provided.al2023) Bash handler
├── scripts/
│   ├── rollout_guard.sh             # 7-state Kubernetes progressive rollout & LKG auto-rollback controller
│   └── validate_config.sh           # Pre-flight size (1 MiB), YAML/JSON schema, SHA-256 & Ed25519 validator
├── security/public/
│   └── ed25519-public.pem           # Public key for verifying signed configuration candidates
├── terraform/
│   ├── main.tf                      # Versioned S3 config store, encryption & public access block
│   ├── iam.tf                       # Least-privilege S3 controller IAM policy
│   ├── vpc.tf                       # Zero-NAT VPC, public subnets, S3 Gateway Endpoint & Security Groups
│   ├── aws_extension.tf             # EventBridge rule, Bash Lambda, live alias & IAM-secured API Gateway
│   ├── cicd_and_data.tf             # ECR, CodeBuild, CodeDeploy Canary, CloudWatch Alarm, DynamoDB & Glue
│   ├── codepipeline.tf              # AWS CodePipeline with Source, CodeBuild & Manual SRE Approval stages
│   ├── variables.tf                 # Configurable region, bucket name & environment tags
│   └── outputs.tf                   # Exported S3, IAM, ECR & API Gateway endpoints
├── appspec.yml                      # AWS CodeDeploy Lambda traffic shifting specification
└── buildspec.yml                    # AWS CodeBuild phases & JUnit XML test report specification
```

---

## Verified AWS Execution Evidence (`evidence/`)

To keep AWS Free Tier costs near zero, billable cloud resources are provisioned via Terraform, tested end-to-end, captured in dated evidence artifacts inside `evidence/`, and cleanly torn down:

* **`evidence/terraform-outputs-*.txt`**: Live Terraform outputs confirming provisioning of the versioned S3 bucket (`arn:aws:s3:::blast-radius-guard-383071508649`), least-privilege IAM policy, and API Gateway `/validate` endpoint (`https://msv0v1i0z0.execute-api.ap-south-1.amazonaws.com/validate`).
* **`evidence/codedeploy-canary-rollback-*.json`**: Output from `aws deploy get-deployment` demonstrating an active `CodeDeployDefault.LambdaCanary10Percent5Minutes` deployment on `blast-radius-config-validator:live` halting and triggering an automatic rollback deployment when the CloudWatch alarm (`blast-radius-lambda-errors`) fires.
* **`evidence/dynamodb-sre-audit-*.json`**: Output from `aws dynamodb scan` on `blast-radius-rollout-audit` showing persisted rollout state transitions, SHA-256 digests, and remaining SLO error budget percentages.
* **`evidence/apigw-sigv4-validate-*.json`**: Output from `curl --aws-sigv4` invoking `POST /validate` on API Gateway and returning the verified SHA-256 payload digest from the Bash Lambda runtime.

---

## Quick Start & Verification Commands

### 1. Run the Pure Bash Validation Suite Locally

```bash
# Validate a known-good config and an Ed25519-signed config
./scripts/validate_config.sh config/candidate-valid.yaml
./scripts/validate_config.sh config/candidate-v1.4.yaml config/candidate-v1.4.yaml.sig security/public/ed25519-public.pem

# Verify malformed and >1 MiB configs are rejected (returns non-zero exit code)
! ./scripts/validate_config.sh config/candidate-broken.yaml
! ./scripts/validate_config.sh config/candidate-oversized.yaml
```

### 2. Build & Smoke-Test the Non-Root Bash Consumer Container

```bash
docker build -t k8s-config-consumer:local -f consumer/Dockerfile consumer/
docker run -d --rm --name consumer-test -p 8000:8000 k8s-config-consumer:local

curl -sS http://localhost:8000/healthz | jq .
curl -sS http://localhost:8000/metrics

docker stop consumer-test
```

### 3. Provision AWS Infrastructure & Test SigV4 API Gateway

```bash
(cd lambda && zip -q ../config-validator-lambda.zip bootstrap)
terraform -chdir=terraform init
terraform -chdir=terraform apply -var="bucket_name=blast-radius-guard-$(aws sts get-caller-identity --query Account --output text)" -auto-approve

API_URL=$(terraform -chdir=terraform output -raw validate_api_endpoint)
curl -sS -X POST "$API_URL" \
  --aws-sigv4 "aws:amz:ap-south-1:execute-api" \
  --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" \
  -H "Content-Type: text/plain" \
  --data-binary @config/candidate-valid.yaml
```

### 4. Run Progressive Cell Rollout & Auto-Rollback

```bash
kubectl apply -f deploy/monitoring/
kubectl apply -f deploy/cells/

# Happy path promotion across blast-cell-1 -> blast-cell-2 -> blast-cell-3
./scripts/rollout_guard.sh config/candidate-v1.4.yaml config/candidate-v1.4.yaml.sig

# Failure injection path (triggers automatic LKG SHA-256 rollback)
./scripts/rollout_guard.sh config/candidate-v1.5-failure.yaml || true
```

### 5. Cost-Safe AWS Teardown

After saving dated verification artifacts to `evidence/`, destroy billable AWS resources while keeping git-tracked evidence intact:

```bash
terraform -chdir=terraform destroy -var="bucket_name=blast-radius-guard-383071508649" -auto-approve
```
