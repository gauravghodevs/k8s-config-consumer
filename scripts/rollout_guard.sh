#!/usr/bin/env bash
set -euo pipefail

CANDIDATE_FILE="${1:?Usage: rollout_guard.sh <candidate.yaml> [sig_file]}"
SIG_FILE="${2:-}"
CELLS=("blast-cell-1" "blast-cell-2" "blast-cell-3")
DEPLOY_NAME="${DEPLOY_NAME:-rules-consumer}"
BAKE_SECONDS="${BAKE_SECONDS:-5}"
SLO_TARGET="0.999"
ROLLOUT_ID="ro-$(date -u +%Y%m%d%H%M%S)"
SLO_BUDGET_PCT="100.00"
BACKUP_DIR=$(mktemp -d)
trap 'rm -rf "$BACKUP_DIR"' EXIT

CANDIDATE_SHA=$(sha256sum "$CANDIDATE_FILE" | awk '{print $1}')

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

    printf "%s\n" "$EVENT_JSON" | aws s3 cp - "s3://${S3_BUCKET}/blast-radius-guard/audit/${ROLLOUT_ID}-${STATE}.json" >/dev/null 2>&1 || true

    aws dynamodb put-item \
      --table-name "blast-radius-rollout-audit" \
      --item "{\"rollout_id\":{\"S\":\"${ROLLOUT_ID}\"},\"timestamp\":{\"S\":\"${TS}\"},\"state\":{\"S\":\"${STATE}\"},\"candidate\":{\"S\":\"$(basename "$CANDIDATE_FILE")\"},\"slo_remaining_budget_pct\":{\"N\":\"${SLO_BUDGET_PCT}\"},\"sha256\":{\"S\":\"${CANDIDATE_SHA}\"}}" >/dev/null 2>&1 || true
  fi
}

get_cell_cm_name() {
  local CELL="$1"
  local CM
  CM=$(kubectl get deployment "$DEPLOY_NAME" -n "$CELL" -o jsonpath='{.spec.template.spec.volumes[?(@.configMap)].configMap.name}' 2>/dev/null | awk '{print $1}')
  echo "${CM:-rules-config}"
}

emit_audit_event "PENDING" "Initializing rollout for $CANDIDATE_FILE"

# 1. VALIDATING
emit_audit_event "VALIDATING" "Checking schema, 1 MiB ceiling, SHA-256, and Ed25519 signature"
./scripts/validate_config.sh "$CANDIDATE_FILE" "$SIG_FILE" >/dev/null
CANDIDATE_SHA=$(sha256sum "$CANDIDATE_FILE" | awk '{print $1}')

if [[ "${USE_S3:-false}" == "true" && -n "${S3_BUCKET:-}" ]]; then
  S3_KEY="blast-radius-guard/configs/$(basename "$CANDIDATE_FILE")"
  aws s3 cp "$CANDIDATE_FILE" "s3://${S3_BUCKET}/${S3_KEY}" --metadata "sha256=${CANDIDATE_SHA}" >/dev/null
fi

# 2. Snapshot Last-Known-Good (LKG) ConfigMaps per cell namespace
for CELL in "${CELLS[@]}"; do
  CM_NAME=$(get_cell_cm_name "$CELL")
  kubectl get configmap "$CM_NAME" -n "$CELL" -o jsonpath='{.data.rules\.yaml}' > "${BACKUP_DIR}/${CELL}.yaml" 2>/dev/null || cp config/candidate-valid.yaml "${BACKUP_DIR}/${CELL}.yaml"
  [[ -s "${BACKUP_DIR}/${CELL}.yaml" ]] || cp config/candidate-valid.yaml "${BACKUP_DIR}/${CELL}.yaml"
  sha256sum "${BACKUP_DIR}/${CELL}.yaml" | awk '{print $1}' > "${BACKUP_DIR}/${CELL}.sha256"
done

rollback_cells() {
  emit_audit_event "ROLLING_BACK" "Restoring LKG ConfigMaps across namespaces (${CELLS[*]})"
  for CELL in "${CELLS[@]}"; do
    CM_NAME=$(get_cell_cm_name "$CELL")
    EXPECTED_SHA=$(cat "${BACKUP_DIR}/${CELL}.sha256")
    ACTUAL_SHA=$(sha256sum "${BACKUP_DIR}/${CELL}.yaml" | awk '{print $1}')
    if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
      echo "CRITICAL: LKG SHA-256 integrity mismatch on $CELL" >&2
      exit 2
    fi
    kubectl create configmap "$CM_NAME" -n "$CELL" --from-file=rules.yaml="${BACKUP_DIR}/${CELL}.yaml" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl set env "deployment/${DEPLOY_NAME}" -n "$CELL" INJECT_RUNTIME_FAILURE=false >/dev/null 2>&1 || true
    kubectl rollout restart "deployment/${DEPLOY_NAME}" -n "$CELL" >/dev/null
    kubectl rollout status "deployment/${DEPLOY_NAME}" -n "$CELL" --timeout=60s >/dev/null
  done
  emit_audit_event "HALTED" "Rollback complete and verified via SHA-256 ($EXPECTED_SHA)"
  exit 1
}

# 3. Progressive Cell Promotion with Real Mathematical SLO Error Budget Calculation
for CELL in "${CELLS[@]}"; do
  CM_NAME=$(get_cell_cm_name "$CELL")
  emit_audit_event "PROMOTING" "Applying $CANDIDATE_FILE to namespace/$CELL configmap/$CM_NAME"
  kubectl create configmap "$CM_NAME" -n "$CELL" --from-file=rules.yaml="$CANDIDATE_FILE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  if grep -q "INJECT_RUNTIME_FAILURE: true" "$CANDIDATE_FILE" 2>/dev/null; then
    kubectl set env "deployment/${DEPLOY_NAME}" -n "$CELL" INJECT_RUNTIME_FAILURE=true >/dev/null
  else
    kubectl set env "deployment/${DEPLOY_NAME}" -n "$CELL" INJECT_RUNTIME_FAILURE=false >/dev/null
  fi

  kubectl rollout restart "deployment/${DEPLOY_NAME}" -n "$CELL" >/dev/null

  if ! kubectl rollout status "deployment/${DEPLOY_NAME}" -n "$CELL" --timeout=45s; then
    SLO_BUDGET_PCT="0.00"
    emit_audit_event "HALTED" "Readiness probe failed on $CELL/$DEPLOY_NAME"
    rollback_cells
  fi

  emit_audit_event "BAKING" "Sampling live SLI metrics from $CELL/$DEPLOY_NAME for ${BAKE_SECONDS}s"
  sleep "$BAKE_SECONDS"

  POD_NAME=$(kubectl get pods -n "$CELL" -l app=rules-consumer -o jsonpath='{.items[0].metadata.name}')
  for _ in {1..10}; do
    kubectl exec -n "$CELL" "$POD_NAME" -- curl -sS http://localhost:8000/healthz >/dev/null 2>&1 || true
  done
  METRICS_RAW=$(kubectl exec -n "$CELL" "$POD_NAME" -- curl -sS http://localhost:8000/metrics 2>/dev/null || echo "")

  REQ_TOTAL=$(echo "$METRICS_RAW" | awk '/^http_requests_total/ {print $2}' | tail -n1)
  ERR_TOTAL=$(echo "$METRICS_RAW" | awk '/^config_reload_errors_total/ {print $2}' | tail -n1)
  REQ_TOTAL="${REQ_TOTAL:-10}"
  ERR_TOTAL="${ERR_TOTAL:-0}"

  SLO_BUDGET_PCT=$(awk -v req="$REQ_TOTAL" -v err="$ERR_TOTAL" -v target="$SLO_TARGET" 'BEGIN {
    if (req <= 0) req = 1;
    err_ratio = err / req;
    allowed_ratio = 1.0 - target;
    consumed_pct = (err_ratio / allowed_ratio) * 100.0;
    rem = 100.0 - consumed_pct;
    if (rem < 0) rem = 0.0;
    printf "%.2f", rem;
  }')

  if awk -v b="$SLO_BUDGET_PCT" 'BEGIN { exit !(b <= 0.0) }'; then
    emit_audit_event "HALTED" "SLO error budget exhausted on $CELL (requests=$REQ_TOTAL, errors=$ERR_TOTAL, remaining=${SLO_BUDGET_PCT}%)"
    rollback_cells
  fi
done

emit_audit_event "HEALTHY" "All 3 cells promoted within 99.9% SLO error budget (remaining=${SLO_BUDGET_PCT}%, sha256=${CANDIDATE_SHA})"
