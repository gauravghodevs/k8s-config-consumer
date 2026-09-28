# Blast-Radius Guard

> Staged configuration delivery with automatic health-gated promotion and cross-cell rollback for Kubernetes-based platform/SRE systems.

## Overview

Blast-Radius Guard is a local Kubernetes simulation of a production-style configuration rollout controller.

The system prevents a valid-looking but unsafe configuration from being immediately propagated across every cell.

A candidate configuration is:

1. Validated before deployment
2. Promoted through controlled stages
3. Health-checked after activation
4. Baked for a defined period
5. Automatically halted if health checks fail
6. Rolled back to the previous known-good configuration

### Rollout Model

```text
Candidate Configuration
          |
          v
     VALIDATING
          |
          v
      PROMOTING
          |
          v
       INTERNAL
          |
        BAKING
          |
       HEALTHY
          |
          v
          1%
          |
        BAKING
          |
       HEALTHY
          |
          v
          10%
          |
        BAKING
          |
       HEALTHY
          |
          v
         100%
          |
       HEALTHY
          |
          v
      COMPLETED

if validation or health checks fail:
FAILED
   |
   v
HALTED
   |
   v
ROLLING_BACK
   |
   v
Previous Known-Good Configuration
```

## Key Capabilities

- Schema and semantic configuration validation
- Staged promotion across isolated Kubernetes cells
- Health-gated bake periods
- SHA256 verification of active configuration
- Prometheus-compatible consumer metrics
- Last-known-good configuration protection
- Automatic cross-cell rollback
- Persistent controller state tracking
- Kubernetes ConfigMap-based configuration delivery
- Python-based rollout controller
- Automated contract tests in CI

## Technology Stack

- **Kubernetes:** Kind
- **Container Runtime:** Docker
- **Language:** Python
- **Configuration:** YAML
- **Validation:** JSON Schema + semantic validation
- **Metrics:** Prometheus client
- **CI/CD:** GitHub Actions
- **Version Control:** Git + GitHub

## Architecture 
                    Candidate Configuration
                             |
                             v
                    +------------------+
                    |  Rollout Guard   |
                    | Python Controller |
                    +--------+---------+
                             |
                       Validation
                    Schema + Semantics
                             |
                             v
                 +-----------------------+
                 | Kubernetes ConfigMap  |
                 |      rules-config     |
                 +-----------+-----------+
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
        +-----------+  +-----------+  +-----------+
        |  Cell 1   |  |  Cell 2   |  |  Cell 3   |
        | INTERNAL  |  |   ~10%    |  |   100%    |
        +-----+-----+  +-----+-----+  +-----+-----+
              |              |              |
              v              v              v
        +-----------+  +-----------+  +-----------+
        | Consumer  |  | Consumer  |  | Consumer  |
        | /health   |  | /health   |  | /health   |
        | /ready    |  | /ready    |  | /ready    |
        | /metrics  |  | /metrics  |  | /metrics  |
        +-----------+  +-----------+  +-----------+
              |
              v
       Health + SHA256 Checks
              |
       +------+------+ 
       |             |
     HEALTHY       FAILURE
       |             |
       v             v
   Next Stage     HALTED
                     |
                     v
                ROLLING_BACK
                     |
                     v
             Known-Good Config
```

### Consumer

Each Kubernetes cell runs a lightweight Python configuration consumer.

The consumer:

- Loads `rules.yaml` from a Kubernetes ConfigMap
- Validates schema and semantic rules
- Maintains the last-known-good configuration
- Detects configuration changes using SHA256
- Exposes health and readiness endpoints
- Exposes Prometheus-compatible metrics

Endpoints:

- `/health`
- `/ready`
- `/metrics`

### Rollout Controller

The Python rollout controller manages the complete promotion lifecycle.

Responsibilities:

- Validate candidate configurations before rollout
- Save previous configurations for rollback
- Promote configurations across cells
- Wait for configuration activation
- Execute health-gated bake periods
- Detect reload failures and configuration mismatches
- Halt failed rollouts
- Restore previous known-good configurations across affected cells
- Persist rollout state for operational visibility

Rollout flow:

`PENDING → VALIDATING → PROMOTING → BAKING → HEALTHY → COMPLETED`

Failure path:

`HALTED → ROLLING_BACK → Previous Known-Good Configuration`

### Configuration Validation

Every candidate configuration passes two layers of validation before promotion:

1. **Schema validation** — verifies the expected YAML structure and data types using JSON Schema.
2. **Semantic validation** — rejects unsafe or invalid rule values such as dangerous rule names, invalid actions, duplicate rule names, and out-of-range priorities.

Invalid candidates are rejected before they can be promoted to any Kubernetes cell.

### Rollback and Safety

Blast-Radius Guard maintains the previous known-good configuration for every cell modified during a rollout.

If a health check fails during promotion:

1. The rollout enters `HALTED` state.
2. The controller transitions to `ROLLING_BACK`.
3. Previously saved configurations are restored in reverse promotion order.
4. Consumer-level last-known-good protection prevents an invalid configuration from becoming active.
5. The rollout does not continue to subsequent stages.

This provides cross-cell rollback for all cells affected before the failure was detected.

## Testing

The project includes automated and manual tests covering configuration safety and staged rollout behavior.

### Validation Tests

- Invalid schema types are rejected.
- Invalid rule actions are rejected.
- Dangerous rule names are rejected.
- Duplicate rule names are rejected.
- Out-of-range priorities are rejected.
- Consumer contract tests pass in CI.

### Rollout Tests

- Successful staged rollout from candidate validation through `100%`.
- Candidate activation verified using SHA256 checks.
- Health and readiness verified at each promotion stage.
- Reload failure metrics monitored during bake periods.
- Forced failure during staged promotion verified the `HALTED → ROLLING_BACK` path.
- Previously active configurations were restored across affected cells.

## Prerequisites

- Linux environment or WSL2
- Docker
- Kubernetes CLI (`kubectl`)
- Kind
- Python 3.11+
- Git

Verify the tools before starting:

```bash
python3 --version
docker --version
kubectl version --client
kind version
git --version
```

## Setup & Installation

Clone the repository:

```bash
git clone <your-repository-url>
cd blast-radius-guard
```

Create the Kind cluster:

```bash
kind create cluster --name devops
```

Create the Kubernetes namespaces:

```bash
kubectl create namespace blast-cell-1
kubectl create namespace blast-cell-2
kubectl create namespace blast-cell-3
```

Build and load the consumer image:

```bash
docker build -t blast-consumer:dev ./consumer
kind load docker-image blast-consumer:dev --name devops
```

Deploy the configuration consumers and Kubernetes resources from the repository manifests.

## Rollout Usage

Run the rollout controller from the repository root:

```bash
python3 controller/rollout_guard.py config/candidate-valid.yaml
```

The controller validates the candidate and promotes it through:

```text
INTERNAL → 1% → 10% → 100%
```

Each stage waits for the candidate configuration to become active, performs health checks, and executes the configured bake period before continuing.

For a failed rollout, the controller transitions to `HALTED` and restores the previously saved configurations across affected cells.

## Configuration Example

A candidate configuration uses a version and a list of rules:

```yaml
version: "1.2"
rules:
  - name: block_bad_ip_v2
    action: deny
    priority: 150

  - name: allow_internal
    action: allow
    priority: 10
```

The configuration is validated before promotion and must satisfy both schema and semantic validation rules.

The configuration is validated before promotion and must satisfy both schema and semantic validation rules.

## Metrics

The consumer exposes Prometheus-compatible metrics through `/metrics`.

Key metrics include:

```text
rules_config_loaded
rules_config_version
rules_config_reload_success_total
rules_config_reload_failure_total
rules_config_last_reload_timestamp
```

The rollout controller uses these metrics together with health checks and SHA256 verification to determine whether a candidate configuration is healthy before promotion.

## Running Tests

Run the consumer contract tests from the repository root:

```bash
python3 -m pytest tests/test_consumer_contract.py -v
```

Validate the rollout controller syntax:

```bash
python3 -m py_compile controller/rollout_guard.py
```

A successful validation should show passing contract tests and no Python syntax errors.

## Project Structure

```text
blast-radius-guard/
├── config/                    # Candidate configuration files
├── consumer/                  # Configuration consumer service
│   ├── app/                   # Consumer application
│   ├── schema/                # JSON Schema definitions
│   └── tests/                 # Consumer contract tests
├── controller/                # Rollout controller
├── deploy/                    # Kubernetes deployment manifests
│   └── cells/                 # Cell-specific resources
├── k8s/                       # Kubernetes resources
├── tests/                     # Project-level tests
├── .github/workflows/         # CI pipeline
└── README.md
```

### Controller State Machine 
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

On failure

HALTED
   |
   v
ROLLING_BACK
```

### Kubernetes Cells

The local Kind environment uses three isolated Kubernetes namespaces:

- `blast-cell-1`
- `blast-cell-2`
- `blast-cell-3`

Each cell contains its own `rules-consumer` Deployment and `rules-config` ConfigMap.

The rollout stages are simulated locally:

```text
INTERNAL  →  1%  →  10%  →  100%
```

### Controller Manager

```text 
PENDING
   ↓
VALIDATING
   ↓
PROMOTING
   ↓
BAKING
   ↓
HEALTHY
   ↓
COMPLETED

#when a roll out fails 
HALTED
   ↓
ROLLING_BACK
   ↓
Previous Known-Good Configuration
```
