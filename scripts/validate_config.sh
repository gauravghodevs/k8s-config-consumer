#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${1:?Usage: validate_config.sh <config.yaml> [sig_file] [pub_key]}"
SIG_FILE="${2:-}"
PUB_KEY="${3:-security/public/ed25519-public.pem}"
SCHEMA_FILE="${SCHEMA_FILE:-consumer/schema/rules.schema.json}"
MAX_BYTES=1048576

[[ -f "$CONFIG_FILE" ]] || { echo "ERROR: Missing config file: $CONFIG_FILE" >&2; exit 1; }
[[ -f "$SCHEMA_FILE" ]] || { echo "ERROR: Missing schema file: $SCHEMA_FILE" >&2; exit 1; }

FILE_SIZE=$(wc -c < "$CONFIG_FILE" | tr -d ' ')
if (( FILE_SIZE == 0 || FILE_SIZE > MAX_BYTES )); then
  echo "ERROR: Invalid size ($FILE_SIZE bytes)." >&2
  exit 1
fi

if ! JSON_DOC=$(yq eval -o=json "$CONFIG_FILE" 2>/dev/null); then
  echo "ERROR: Invalid YAML syntax in $CONFIG_FILE" >&2
  exit 1
fi

if [[ -z "$JSON_DOC" || "$JSON_DOC" == "null" ]]; then
  echo "ERROR: Empty YAML document in $CONFIG_FILE" >&2
  exit 1
fi

printf '%s\n' "$JSON_DOC" \
  | jq -e -s '
    def check:
      (if (.[0].type != null) then
        if (.[0].type == "integer") then
          ((.[1] | type) == "number") and ((.[1] % 1) == 0)
        else
          ((.[1] | type) == .[0].type)
        end
      else true end)
      and
      (if (.[0].enum != null) then
        (([.[1]] - .[0].enum) | length == 0)
      else true end)
      and
      (if ((.[1] | type) == "string") then
        (if (.[0].minLength != null) then ((.[1] | length) >= .[0].minLength) else true end) and
        (if (.[0].maxLength != null) then ((.[1] | length) <= .[0].maxLength) else true end)
      else true end)
      and
      (if ((.[1] | type) == "number") then
        (if (.[0].minimum != null) then (.[1] >= .[0].minimum) else true end) and
        (if (.[0].maximum != null) then (.[1] <= .[0].maximum) else true end)
      else true end)
      and
      (if ((.[1] | type) == "object") then
        (((.[0].required // []) - (.[1] | keys)) | length == 0)
        and
        (if (.[0].additionalProperties == false and .[0].properties != null) then
          (((.[1] | keys) - (.[0].properties | keys)) | length == 0)
        else true end)
        and
        (
          [ (.[0].properties // {} | to_entries[]), (.[1] | to_entries[]) ]
          | group_by(.key)
          | map(select(length == 2) | [.[0].value, .[1].value])
          | all(.[]; check)
        )
      else true end)
      and
      (if ((.[1] | type) == "array") then
        (if (.[0].minItems != null) then ((.[1] | length) >= .[0].minItems) else true end)
        and
        (if (.[0].maxItems != null) then ((.[1] | length) <= .[0].maxItems) else true end)
        and
        (if (.[0].items != null and (.[1] | length) > 0) then
          [ [.[0].items], .[1] ]
          | [ combinations ]
          | all(.[]; check)
        else true end)
      else true end);

    (length == 2)
    and check
    and (
      ((.[1].rules // []) | map(select(type == "object" and has("id")) | .id) | length)
      ==
      ((.[1].rules // []) | map(select(type == "object" and has("id")) | .id) | unique | length)
    )
    and (
      ((.[1].rules // []) | map(select(type == "object" and has("name")) | .name) | length)
      ==
      ((.[1].rules // []) | map(select(type == "object" and has("name")) | .name) | unique | length)
    )
  ' "$SCHEMA_FILE" - >/dev/null || {
  echo "ERROR: JSON Schema or duplicate rule ID/name validation failed for $CONFIG_FILE" >&2
  exit 1
}

SHA256_HASH=$(sha256sum "$CONFIG_FILE" | cut -d' ' -f1)

if [[ -n "$SIG_FILE" ]]; then
  [[ -f "$SIG_FILE" ]] || { echo "ERROR: Signature file not found: $SIG_FILE" >&2; exit 1; }
  TMP_SIG=$(mktemp)
  base64 -d "$SIG_FILE" > "$TMP_SIG"
  if ! openssl pkeyutl -verify -pubin \
    -inkey "$PUB_KEY" \
    -rawin -in "$CONFIG_FILE" \
    -sigfile "$TMP_SIG" >/dev/null 2>&1; then
    rm -f "$TMP_SIG"
    echo "ERROR: Ed25519 signature verification failed for $CONFIG_FILE" >&2
    exit 1
  fi
  rm -f "$TMP_SIG"
fi

printf '{"status":"VALID","file":"%s","sha256":"%s","bytes":%d}\n' \
  "$CONFIG_FILE" "$SHA256_HASH" "$FILE_SIZE"
