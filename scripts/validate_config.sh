#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${1:?Usage: validate_config.sh <config.yaml> [sig_file] [pub_key]}"
SIG_FILE="${2:-}"
PUB_KEY="${3:-security/public/ed25519-public.pem}"
MAX_BYTES=1048576 # 1 MiB

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: File not found: $CONFIG_FILE" >&2
  exit 1
fi

# 1. Size check (1 MiB limit)
FILE_SIZE=$(wc -c < "$CONFIG_FILE" | tr -d ' ')
if (( FILE_SIZE == 0 || FILE_SIZE > MAX_BYTES )); then
  echo "ERROR: Invalid size ($FILE_SIZE bytes). Limit is $MAX_BYTES bytes." >&2
  exit 1
fi

# 2. YAML syntax and convert to JSON
JSON_PAYLOAD=$(yq eval -o=json "$CONFIG_FILE" 2>/dev/null) || {
  echo "ERROR: Malformed YAML in $CONFIG_FILE" >&2
  exit 1
}

# 3. Schema & semantic validation using jq
echo "$JSON_PAYLOAD" | jq -e '
  type == "object" and
  (.version != null and (.version | type == "string") and (.version | length > 0)) and
  (.rules != null and (.rules | type == "array") and (.rules | length > 0)) and
  (all(.rules[]; (.name != null and (.name | type == "string") and (.name | length > 0)) and (.action == "allow" or .action == "deny" or .action == "rate_limit")))
' >/dev/null || {
  echo "ERROR: Schema or semantic rule validation failed for $CONFIG_FILE" >&2
  exit 1
}

# 4. Compute SHA-256
SHA256_HASH=$(sha256sum "$CONFIG_FILE" | awk '{print $1}')

# 5. Optional Ed25519 signature check (for CodeBuild / local controller)
if [[ -n "$SIG_FILE" && -f "$SIG_FILE" ]]; then
  TMP_SIG=$(mktemp)
  trap 'rm -f "$TMP_SIG"' EXIT
  base64 -d "$SIG_FILE" > "$TMP_SIG"
  openssl pkeyutl -verify -pubin -inkey "$PUB_KEY" -rawin -in "$CONFIG_FILE" -sigfile "$TMP_SIG" >/dev/null || {
    echo "ERROR: Ed25519 signature verification failed for $CONFIG_FILE" >&2
    exit 1
  }
fi

jq -n --arg status "VALID" --arg file "$CONFIG_FILE" --arg sha256 "$SHA256_HASH" --argjson bytes "$FILE_SIZE" \
  '{status: $status, file: $file, sha256: $sha256, bytes: $bytes}'
