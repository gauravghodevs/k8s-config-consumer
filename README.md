# Blast-Radius Guard

> Staged configuration delivery with automatic validation, health-gated promotion, integrity verification, signed configuration enforcement, and cross-cell rollback for Kubernetes-based platform/SRE systems.

## Overview

Blast-Radius Guard is a production-style configuration rollout controller implemented as a local Kubernetes simulation.

The system prevents a configuration that is syntactically valid but operationally unsafe from being immediately propagated across every deployment cell.

A candidate configuration passes through:

1. Schema validation
2. Semantic validation
3. SHA-256 integrity calculation
4. Optional Ed25519 signature verification
5. Controlled staged promotion
6. Configuration activation verification
7. Health/readiness checks
8. Bake periods
9. Automatic halt on failure
10. Cross-cell rollback to the previous known-good configuration

The rollout stages are simulated locally as:

```text
INTERNAL → 1% → 10% → 100%
```

These percentages represent **logical rollout stages in the local simulation**, not real traffic percentages.

---

## Architecture

```text
                    Candidate Configuration
                             |
                             v
                    +------------------+
                    |  Rollout Guard   |
                    | Python Controller |
                    +--------+---------+
                             |
                             v
                 Schema + Semantic Validation
                             |
                             v
                       SHA-256 Hash
                             |
                    +--------+---------+
                    |                  |
             Signature Required?       |
                    |                  |
                   YES                 NO
                    |                  |
                    v                  |
             Ed25519 Verify            |
                    |                  |
                    +--------+---------+
                             |
                             v
                    S3 Versioned Store
                             |
                             v
                    Promotion Controller
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
   blast-cell-1       blast-cell-2       blast-cell-3
          |                  |                  |
          v                  v                  v
    rules-consumer      rules-consumer      rules-consumer
          |                  |                  |
          +------------------+------------------+
                             |
                     Health / Ready / SHA
                             |
                    +--------+--------+
                    |                 |
                 HEALTHY           FAILURE
                    |                 |
                    v                 v
              Next Stage            HALTED
                                        |
                                        v
                                  ROLLING_BACK
                                        |
                                        v
                              Known-Good Config
```

---

## Key Capabilities

### Configuration safety

* JSON Schema validation
* Semantic validation
* Duplicate rule detection
* Invalid action detection
* Dangerous rule-name validation
* Priority validation
* Maximum configuration size enforcement
* SHA-256 candidate integrity verification

### Progressive delivery

* `INTERNAL`
* `1%`
* `10%`
* `100%`
* Configurable bake periods
* Health/readiness verification before promotion

### Failure protection

* Deterministic runtime failure injection for testing
* Automatic `HALTED` transition
* Automatic `ROLLING_BACK`
* Cross-cell rollback
* Previous configuration preservation
* Consumer-level last-known-good protection
* Rollout state persistence

### Cryptographic verification

* Ed25519 configuration signing
* Detached `.sig` files
* Public-key verification
* Optional mandatory signature enforcement
* Private signing key excluded from Git
* Tampered configuration rejection

### AWS infrastructure

* S3 configuration bucket
* S3 versioning
* Server-side encryption
* Public-access blocking
* Object ownership controls
* Lifecycle configuration
* Least-privilege IAM policy
* Terraform-managed infrastructure

---

## Technology Stack

| Component              | Technology               |
| ---------------------- | ------------------------ |
| Language               | Python 3.11+             |
| Container runtime      | Docker                   |
| Kubernetes             | Kind                     |
| Kubernetes CLI         | kubectl                  |
| Configuration          | YAML                     |
| Schema validation      | JSON Schema              |
| Metrics                | Prometheus client        |
| Object storage         | Amazon S3                |
| Infrastructure as Code | Terraform                |
| Cryptography           | Ed25519 / `cryptography` |
| CI/CD                  | GitHub Actions           |
| Version control        | Git + GitHub             |

---

# Configuration Consumer

Each Kubernetes cell runs a lightweight Python configuration consumer.

The consumer:

* Loads `rules.yaml` from a Kubernetes ConfigMap
* Validates configuration structure
* Performs semantic validation
* Maintains last-known-good configuration
* Detects configuration changes using SHA-256
* Exposes health and readiness endpoints
* Exposes Prometheus-compatible metrics

### Endpoints

```text
/health
/ready
/metrics
```

---

# Rollout Controller

The controller is implemented in:

```text
controller/rollout_guard.py
```

Run it from the repository root:

```bash
controller/.venv/bin/python -m controller.rollout_guard config/candidate-v1.4.yaml
```

The controller manages the rollout state machine:

```text
PENDING
   |
   v
VALIDATING
   |
   v
PROMOTING
   |
   v
BAKING
   |
   v
HEALTHY
   |
   v
COMPLETED
```

Failure path:

```text
HALTED
   |
   v
ROLLING_BACK
   |
   v
Previous Known-Good Configuration
```

---

# Configuration Validation

Every candidate is validated before promotion.

## Schema validation

The consumer schema verifies the expected YAML structure and data types.

## Semantic validation

Semantic validation rejects unsafe configuration values such as:

* Invalid actions
* Duplicate rule names
* Dangerous rule names
* Invalid priorities
* Other invalid rule combinations

## Maximum configuration size

The controller enforces a configurable maximum candidate size.

Default:

```text
1 MiB
```

Override with:

```bash
MAX_CONFIG_SIZE=2097152 \
controller/.venv/bin/python -m controller.rollout_guard config/candidate.yaml
```

---

# SHA-256 Integrity

The controller calculates a SHA-256 hash of the exact candidate bytes:

```text
[VALIDATE] Candidate SHA-256: <hash>
```

When the configuration is uploaded to S3, the stored object's SHA-256 is compared against the candidate hash.

A mismatch causes validation to fail.

This protects against the candidate changing between local validation and storage.

---

# Ed25519 Configuration Signing

Blast-Radius Guard supports cryptographic signing of configuration candidates.

The signing implementation is:

```text
controller/signing.py
```

It uses Ed25519 keys through the Python `cryptography` library.

## Key locations

Public verification key:

```text
security/public/ed25519-public.pem
```

Private signing key:

```text
security/keys/ed25519-private.pem
```

The private key directory is explicitly ignored by Git:

```text
security/keys/
```

The private key must never be committed to the repository.

## Signature format

A candidate can have a detached signature:

```text
config/candidate-v1.4.yaml
config/candidate-v1.4.yaml.sig
```

The controller verifies the signature against the exact candidate bytes.

---

## Enforcing signatures

By default, signature enforcement is disabled.

Enable it with:

```bash
REQUIRE_SIGNATURE=true \
controller/.venv/bin/python -m controller.rollout_guard \
config/candidate-v1.4.yaml
```

The public key defaults to:

```text
security/public/ed25519-public.pem
```

It can be overridden with:

```bash
PUBLIC_KEY_PATH=/path/to/public-key.pem \
REQUIRE_SIGNATURE=true \
controller/.venv/bin/python -m controller.rollout_guard \
config/candidate-v1.4.yaml
```

When signature verification succeeds:

```text
[SIGNATURE] Ed25519 verification passed
```

If the candidate has been modified after signing:

```text
Candidate signature is invalid
```

The rollout is halted before promotion.

---

# S3 Configuration Storage

Terraform provisions the S3 configuration storage used by the controller.

The bucket uses:

* S3 versioning
* Server-side encryption
* Public-access blocking
* Ownership controls
* Lifecycle configuration

The controller stores validated configurations using versioned S3 objects.

The current Terraform resources are under:

```text
terraform/
```

Initialize Terraform:

```bash
cd terraform
terraform init
```

Review the infrastructure:

```bash
terraform plan
```

Apply:

```bash
terraform apply
```

View outputs:

```bash
terraform output
```

Expected outputs include:

```text
bucket_name
bucket_arn
bucket_region
controller_s3_policy_arn
```

---

# Least-Privilege IAM

Terraform creates the controller S3 policy:

```text
blast-radius-guard-controller-s3
```

The policy is restricted to the configuration object path and permits only the required S3 operations.

The policy includes:

```text
s3:GetObject
s3:PutObject
s3:ListBucket
```

The ListBucket permission is restricted to:

```text
blast-radius-guard/configs/*
```

Terraform state and variable files are excluded from Git.

---

# Kubernetes Environment

Create the Kind cluster:

```bash
kind create cluster --name devops
```

Create the three isolated namespaces:

```bash
kubectl create namespace blast-cell-1
kubectl create namespace blast-cell-2
kubectl create namespace blast-cell-3
```

Build the consumer:

```bash
docker build -t blast-consumer:dev ./consumer
```

Load it into Kind:

```bash
kind load docker-image blast-consumer:dev --name devops
```

Deploy the cells:

```bash
kubectl apply -f deploy/cells/
```

Verify:

```bash
kubectl get pods -A
```

---

# Rollout Stages

The local simulation models progressive rollout as:

```text
INTERNAL
   |
   v
1%
   |
   v
10%
   |
   v
100%
```

At each stage the controller:

1. Applies the candidate.
2. Waits for activation.
3. Checks readiness.
4. Checks health.
5. Verifies configuration state.
6. Executes the configured bake period.
7. Promotes only after the stage is healthy.

The percentages are **simulation stages**, not actual weighted Kubernetes or load-balancer traffic.

---

# Bake Periods

Bake durations are configurable through environment variables.

Defaults:

```text
BAKE_INTERNAL=30
BAKE_1_PERCENT=60
BAKE_10_PERCENT=60
```

Example:

```bash
BAKE_INTERNAL=10 \
BAKE_1_PERCENT=20 \
BAKE_10_PERCENT=20 \
controller/.venv/bin/python -m controller.rollout_guard \
config/candidate-v1.4.yaml
```

---

# Prometheus Metrics

The consumer exposes:

```text
/metrics
```

Important metrics include:

```text
rules_config_loaded
rules_config_version
rules_config_reload_success_total
rules_config_reload_failure_total
rules_config_last_reload_timestamp
```

The controller uses health/readiness information together with configuration integrity checks during rollout.

---

# Failure Injection

The controller includes deterministic runtime failure injection for testing the safety path.

Enable it with:

```bash
INJECT_RUNTIME_FAILURE=true \
controller/.venv/bin/python -m controller.rollout_guard \
config/candidate-v1.4.yaml
```

A failure should result in:

```text
HALTED
   |
   v
ROLLING_BACK
```

The controller restores configurations previously saved for the affected cells.

This mechanism exists specifically to make the rollback path reproducible during testing.

---

# Rollback

Before modifying a cell, the controller records its existing configuration.

If a later stage fails:

```text
Candidate
   |
   v
HALTED
   |
   v
ROLLING_BACK
   |
   v
Previous Configuration
```

Rollback occurs in reverse promotion order.

The consumer also maintains last-known-good configuration protection.

The combination prevents a failed rollout from continuing to later cells.

---

# Configuration Example

Example candidate:

```yaml
version: "1.4"

rules:
  - name: block_bad_ip_v2
    action: deny
    priority: 150

  - name: allow_internal
    action: allow
    priority: 10
```

The candidate must pass schema and semantic validation before promotion.

---

# Testing

The project contains tests for cryptographic signing as well as the existing consumer/controller functionality.

Run the complete test suite:

```bash
controller/.venv/bin/pytest -q
```

Current verified result:

```text
11 passed
```

Run signing tests specifically:

```bash
controller/.venv/bin/pytest -q tests/test_signing.py
```

Expected:

```text
2 passed
```

The signing tests verify:

1. Valid Ed25519 signatures are accepted.
2. Tampered configuration content fails verification.

---

# Security Checks

Before committing changes, verify sensitive files are ignored:

```bash
git check-ignore -v \
  security/keys/ed25519-private.pem \
  terraform/terraform.tfstate \
  terraform/terraform.tfstate.backup \
  terraform/terraform.tfvars
```

Verify they are not tracked:

```bash
git ls-files | grep -E \
'ed25519-private|terraform.tfstate|terraform.tfvars' \
|| echo "SECURITY CHECK: clean"
```

The repository should never contain:

```text
security/keys/ed25519-private.pem
terraform/*.tfstate
terraform/*.tfstate.*
terraform/*.tfvars
```

---

# Project Structure

```text
blast-radius-guard/
├── config/
│   ├── candidate-*.yaml
│   └── *.sig
│
├── consumer/
│   ├── app/
│   ├── schema/
│   └── requirements.txt
│
├── controller/
│   ├── rollout_guard.py
│   ├── signing.py
│   ├── s3_store.py
│   └── requirements.txt
│
├── deploy/
│   └── cells/
│
├── k8s/
│
├── security/
│   └── public/
│       └── ed25519-public.pem
│
├── terraform/
│   ├── main.tf
│   ├── iam.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── versions.tf
│   └── .terraform.lock.hcl
│
├── tests/
│   ├── test_signing.py
│   └── ...
│
├── .github/
│   └── workflows/
│
├── .gitignore
├── pytest.ini
└── README.md
```

The private signing key is intentionally absent from the repository:

```text
security/keys/ed25519-private.pem
```

---

# Prerequisites

Recommended environment:

* Linux or WSL2
* Python 3.11+
* Docker
* kubectl
* Kind
* Terraform
* Git

Verify:

```bash
python3 --version
docker --version
kubectl version --client
kind version
terraform version
git --version
```

---

# Local Python Environment

Create the controller virtual environment:

```bash
python3 -m venv controller/.venv
```

Install dependencies:

```bash
controller/.venv/bin/pip install -r controller/requirements.txt
```

The controller dependencies include:

```text
boto3
Flask
PyYAML
jsonschema
prometheus-client
cryptography
```

---

# Basic Rollout

From the repository root:

```bash
controller/.venv/bin/python -m controller.rollout_guard \
config/candidate-v1.4.yaml
```

For mandatory signature verification:

```bash
REQUIRE_SIGNATURE=true \
controller/.venv/bin/python -m controller.rollout_guard \
config/candidate-v1.4.yaml
```

A successful validation includes output similar to:

```text
[VALIDATE] Candidate passed schema and semantic validation
[VALIDATE] Config version: 1.4
[VALIDATE] Candidate SHA-256: <hash>
[SIGNATURE] Ed25519 verification passed
```

The controller then proceeds into staged promotion.

---

# Controller State Machine

```text
                    +-------------+
                    |   PENDING   |
                    +------+------+
                           |
                           v
                    +-------------+
                    | VALIDATING  |
                    +------+------+
                           |
                           v
                    +-------------+
                    | PROMOTING   |
                    +------+------+
                           |
                           v
                    +-------------+
                    |   BAKING    |
                    +------+------+
                           |
                           v
                    +-------------+
                    |   HEALTHY   |
                    +------+------+
                           |
                           v
                    +-------------+
                    |  COMPLETED  |
                    +-------------+

Failure from validation or promotion
                           |
                           v
                    +-------------+
                    |   HALTED    |
                    +------+------+
                           |
                           v
                    +-------------+
                    |ROLLING_BACK |
                    +------+------+
                           |
                           v
                 Previous Known-Good
                    Configuration
```

---

# Repository Status

The implementation currently includes:

* Kubernetes configuration consumer
* staged rollout controller
* health-gated promotion
* deterministic rollback testing
* SHA-256 integrity verification
* S3-backed configuration storage
* Terraform AWS infrastructure
* least-privilege S3 IAM policy
* Ed25519 signing and verification
* mandatory signature enforcement
* Prometheus-compatible metrics
* automated tests

The repository is intended as a **production-style DevOps/SRE engineering project and local simulation**, not as a claim that the local Kind environment itself represents a production deployment.

---

## License

This project is provided for engineering, learning, and demonstration purposes.

