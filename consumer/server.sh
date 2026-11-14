#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
CONFIG_PATH="${CONFIG_PATH:-/app/rules.yaml}"
CELL_NAME="${CELL_NAME:-blast-cell-1}"
COUNTER_FILE="/tmp/requests_total"
if [[ ! -f "$COUNTER_FILE" ]]; then
  echo "0" > "$COUNTER_FILE"
fi

if [[ "${1:-}" == "--handle-request" ]]; then
  read -r REQUEST_LINE || true
  REQ_PATH=$(echo "$REQUEST_LINE" | awk '{print $2}')

  while read -r HEADER; do
    if [[ -z "${HEADER//$'\r'/}" ]]; then
      break
    fi
  done

  PREV_COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
  REQ_COUNT=$(( PREV_COUNT + 1 ))
  echo "$REQ_COUNT" > "$COUNTER_FILE"

  ERROR_COUNT=0
  STATUS_MSG="healthy"

  if [[ "${INJECT_RUNTIME_FAILURE:-false}" == "true" ]]; then
    ERROR_COUNT=10
    STATUS_MSG="injected_runtime_failure"
  elif grep -q "INJECT_RUNTIME_FAILURE: true" "$CONFIG_PATH" 2>/dev/null; then
    ERROR_COUNT=10
    STATUS_MSG="injected_runtime_failure"
  elif [[ ! -f "$CONFIG_PATH" ]]; then
    ERROR_COUNT=10
    STATUS_MSG="missing_config"
  fi

  case "$REQ_PATH" in
    /metrics*)
      BODY="# HELP http_requests_total Total HTTP requests processed (SLI)
# TYPE http_requests_total counter
http_requests_total{cell=\"${CELL_NAME}\"} ${REQ_COUNT}
# HELP config_reload_errors_total Total configuration reload errors (SLI)
# TYPE config_reload_errors_total gauge
config_reload_errors_total{cell=\"${CELL_NAME}\"} ${ERROR_COUNT}
"
      LEN="${#BODY}"
      printf "HTTP/1.1 200 OK\r\nContent-Type: text/plain; version=0.0.4\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" \
        "$LEN" \
        "$BODY"
      ;;
    /ready*)
      BODY="{\"status\":\"ready\",\"cell\":\"${CELL_NAME}\"}"
      LEN="${#BODY}"
      printf "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" \
        "$LEN" \
        "$BODY"
      ;;
    /health*|/)
      if (( ERROR_COUNT == 0 )); then
        BODY="{\"status\":\"${STATUS_MSG}\",\"cell\":\"${CELL_NAME}\",\"sli_healthy\":true}"
        LEN="${#BODY}"
        printf "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" \
          "$LEN" \
          "$BODY"
      else
        BODY="{\"status\":\"${STATUS_MSG}\",\"cell\":\"${CELL_NAME}\",\"sli_healthy\":false}"
        LEN="${#BODY}"
        printf "HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" \
          "$LEN" \
          "$BODY"
      fi
      ;;
    *)
      BODY='{"error":"not_found"}'
      LEN="${#BODY}"
      printf "HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" \
        "$LEN" \
        "$BODY"
      ;;
  esac
  exit 0
fi

echo "Starting Pure Bash Config Consumer on port ${PORT}..."
exec socat \
  TCP-LISTEN:"${PORT}",reuseaddr,fork \
  EXEC:"/app/server.sh --handle-request"
