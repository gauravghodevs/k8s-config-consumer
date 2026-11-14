# Blast-Radius Guard (`k8s-config-consumer`)

An automated Kubernetes progressive configuration delivery controller, non-root HTTP consumer microservice, and AWS DevSecOps/SRE validation pipeline implemented in **Bash (`bash`, `jq`, `yq`, `openssl`, `socat`)**, **Terraform (HCL)**, and **Kubernetes**.

## 1. Core Components

* **Schema & Cryptographic Validator (`scripts/validate_config.sh` & `lambda/bootstrap`):**
  * Validates candidate YAML files directly against `consumer/schema/rules.schema.json` (enforcing required top-level fields, allowed rule actions `allow`/`deny`, and unique rule `id` and `name` constraints), a 1 MiB payload ceiling, SHA-256 checksums, and Ed25519 signatures (`security/public/ed25519-public.pem`).
* **Progressive Rollout Controller (`scripts/rollout_guard.sh`):**
  * Implements the state machine (`PENDING` -> `VALIDATING` -> `PROMOTING` -> `BAKING` -> `HEALTHY` / `HALTED` -> `ROLLING_BACK`) across Kubernetes namespaces `blast-cell-1`, `blast-cell-2`, and `blast-cell-3`.
  * Snapshots Last-Known-Good (LKG) ConfigMaps and their SHA-256 hashes before promotion. During each cell's bake window, queries live pod `/metrics` (`http_requests_total` and `config_reload_errors_total`), computes remaining 99.9% SLO error budget, and automatically rolls back all cells if the budget is exhausted.
* **Non-Root Consumer Service (`consumer/server.sh` & `consumer/Dockerfile`):**
  * Runs on Alpine 3.20 as `USER 10001` using `socat`, `jq`, and `yq` to serve `/healthz`, `/readyz`, and Prometheus `/metrics` on port `8000`.
* **Monotonic JUnit Test Runner (`scripts/run_test_suite.sh`):**
  * Executes 7 validation, signature, size, and duplicate-rule checks using `/proc/uptime` monotonic timing to produce `junit-report.xml` for GitHub Actions and AWS CodeBuild.

## 2. Verified Evidence (`evidence/`)

* `evidence/rollout-controller-e2e-*.log` — Full 3-cell promotion of signed `candidate-v1.4.yaml` (`HEALTHY`) followed by runtime failure detection on `candidate-v1.5-runtime-test.yaml` (`BAKING` -> `HALTED` -> `ROLLING_BACK` with SHA-256 LKG restoration).
* `evidence/apigw-sigv4-validate-*.json` — Authenticated `curl --aws-sigv4` request to `POST /validate` returning `{"valid": true, "sha256": "...", "bytes": 143}`.
* `evidence/codedeploy-canary-rollback-*.json` — AWS CodeDeploy canary deployment (`LambdaCanary10Percent5Minutes`) automatic rollback triggered by CloudWatch Alarm `blast-radius-lambda-errors`.
* `evidence/codepipeline-e2e-state-*.json` — Completed end-to-end AWS CodePipeline execution across `Source`, `Build_And_Validate`, `Manual_SRE_Approval`, and `Deploy` stages.
* `evidence/dynamodb-sre-audit-*.json` — Raw `aws dynamodb scan` output from `blast-radius-rollout-audit` containing `PENDING`, `VALIDATING`, `PROMOTING`, `BAKING`, `HEALTHY`, `HALTED`, and `ROLLING_BACK` items.
* `evidence/athena-halted-rollouts-*.json` — Amazon Athena SQL query results over the AWS Glue Data Catalog table (`blast_radius_rollout_db.rollout_events`) returning halted and rolled-back rollouts.
* `evidence/terraform-outputs-*.txt` — Provisioned AWS resource ARNs and API Gateway endpoint in `ap-south-1`.

## 3. Quick Start

```bash
./scripts/run_test_suite.sh junit-report.xml
./scripts/package_lambda.sh
./scripts/rollout_guard.sh config/candidate-v1.4.yaml config/candidate-v1.4.yaml.sig
./scripts/rollout_guard.sh config/candidate-v1.5-runtime-test.yaml
