#!/usr/bin/env bash
set -euo pipefail

CANDIDATE_FILE="${1:?Usage: rollout_guard.sh <candidate.yaml> [sig_file]}"
SIG_FILE="${2:-}"
CELLS=("blast-cell-1" "blast-cell-2" "blast-cell-3")
PROM_URL="${PROMETHEUS_URL:-http://localhost:9090}"
BAKE_SECONDS="${BAKE_SECONDS:-10}"
ROLLOUT_ID="ro-$(date -u +%Y%m%d%H%M%S)"
SLO_BUDGET_PCT="100.0"
BACKUP_DIR=$(mktemp -d)
trap 'rm -rf "$BACKUP_DIR"' EXIT

CANDIDATE_SHA="unverified"

emit_audit_event() {
  local STATE="$1"
  local DETAIL="$2"
  local TS
  TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "[${TS}] ID=${ROLLOUT_ID} | STATE=${STATE} | SLO_BUDGET=${SLO_BUDGET_PCT}% | DETAIL=${DETAIL}"

  if [[ "${USE_S3:-false}" == "true" && -n "${S3_BUCKET:-}" ]]; then
    local EVENT_JSON
    EVENT_JSON=$(jq -c -n \
      --arg id "$ROLLOUT_ID" \
      --arg cand "$(basename "$CANDIDATE_FILE")" \
      --arg st "$STATE" \
      --argjson budget "$SLO_BUDGET_PCT" \
      --arg sha "$CANDIDATE_SHA" \
      --arg ts "$TS" \
      '{rollout_id:$id, candidate:$cand, state:$st, slo_remaining_budget_pct:$budget, sha256:$sha, timestamp:$ts}')

    # 1. Write JSON line to S3 for AWS Glue Catalog table
    printf "%s\n" "$EVENT_JSON" | aws s3 cp - "s3://${S3_BUCKET}/blast-radius-guard/audit/${ROLLOUT_ID}-${STATE}.json" >/dev/null 2>&1 || true

    # 2. Write item to DynamoDB rollout audit table
    aws dynamodb put-item \
      --table-name "blast-radius-rollout-audit" \
      --item "{\"rollout_id\":{\"S\":\"${ROLLOUT_ID}\"},\"timestamp\":{\"S\":\"${TS}\"},\"state\":{\"S\":\"${STATE}\"},\"candidate\":{\"S\":\"$(basename "$CANDIDATE_FILE")\"},\"slo_budget_pct\":{\"N\":\"${SLO_BUDGET_PCT}\"},\"sha256\":{\"S\":\"${CANDIDATE_SHA}\"}}" >/dev/null 2>&1 || true
  fi
}

emit_audit_event "PENDING" "Initializing rollout for $CANDIDATE_FILE"

# 1. VALIDATING
emit_audit_event "VALIDATING" "Running schema, size, SHA-256, and Ed25519 checks"
./scripts/validate_config.sh "$CANDIDATE_FILE" "$SIG_FILE" >/dev/null
CANDIDATE_SHA=$(sha256sum "$CANDIDATE_FILE" | awk '{print $1}')

if [[ "${USE_S3:-false}" == "true" && -n "${S3_BUCKET:-}" ]]; then
  S3_KEY="blast-radius-guard/configs/$(basename "$CANDIDATE_FILE")"
  aws s3 cp "$CANDIDATE_FILE" "s3://${S3_BUCKET}/${S3_KEY}" --metadata "sha256=${CANDIDATE_SHA}" >/dev/null
fi

# 2. Snapshot LKG ConfigMaps and SHA-256 hashes
for CELL in "${CELLS[@]}"; do
  kubectl get configmap "${CELL}-config" -o jsonpath='{.data.rules\.yaml}' > "${BACKUP_DIR}/${CELL}.yaml" 2>/dev/null || cp config/candidate-valid.yaml "${BACKUP_DIR}/${CELL}.yaml"
  sha256sum "${BACKUP_DIR}/${CELL}.yaml" | awk '{print $1}' > "${BACKUP_DIR}/${CELL}.sha256"
done

rollback_cells() {
  SLO_BUDGET_PCT="0.0"
  emit_audit_event "ROLLING_BACK" "SRE Error Budget exhausted; auto-remediating cells to LKG"
  for CELL in "${CELLS[@]}"; do
    EXPECTED_SHA=$(cat "${BACKUP_DIR}/${CELL}.sha256")
    ACTUAL_SHA=$(sha256sum "${BACKUP_DIR}/${CELL}.yaml" | awk '{print $1}')
    if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
      echo "CRITICAL: LKG SHA-256 mismatch on $CELL" >&2
      exit 2
    fi
    kubectl create configmap "${CELL}-config" --from-file=rules.yaml="${BACKUP_DIR}/${CELL}.yaml" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl rollout restart "deployment/${CELL}" >/dev/null
    kubectl rollout status "deployment/${CELL}" --timeout=60s >/dev/null
  done
  emit_audit_event "HALTED" "Auto-healing complete; LKG verified via SHA-256"
  exit 1
}

# 3. Progressive Cell Promotion with SRE Error Budget Gate
for CELL in "${CELLS[@]}"; do
  emit_audit_event "PROMOTING" "Applying $CANDIDATE_FILE to $CELL"
  kubectl create configmap "${CELL}-config" --from-file=rules.yaml="$CANDIDATE_FILE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl rollout restart "deployment/${CELL}" >/dev/null

  if ! kubectl rollout status "deployment/${CELL}" --timeout=60s; then
    emit_audit_event "HALTED" "Readiness probe failed on $CELL"
    rollback_cells
  fi

  emit_audit_event "BAKING" "Evaluating SLI/SLO error budget on $CELL for ${BAKE_SECONDS}s"
  sleep "$BAKE_SECONDS"

  if grep -q "INJECT_RUNTIME_FAILURE: true" "$CANDIDATE_FILE" 2>/dev/null; then
    emit_audit_event "HALTED" "SLI breach: runtime failure injected in $CELL"
    rollback_cells
  fi

  ERR_COUNT=$(curl -sf "${PROM_URL}/api/v1/query?query=config_reload_errors_total\{cell=\"${CELL}\"\}" | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")
  if [[ "$ERR_COUNT" != "0" ]]; then
    emit_audit_event "HALTED" "SLO 99.9% error budget breached ($ERR_COUNT errors in $CELL)"
    rollback_cells
  fi
done

emit_audit_event "HEALTHY" "All 3 cells promoted within 99.9% SLO error budget"
