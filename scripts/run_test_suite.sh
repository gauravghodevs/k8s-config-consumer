#!/usr/bin/env bash
set -uo pipefail

REPORT_FILE="${1:-junit-report.xml}"
TOTAL=0
FAILURES=0
TESTCASES_XML=""

run_case() {
  local NAME="$1"
  local EXPECT_PASS="$2"
  shift 2
  TOTAL=$((TOTAL + 1))

  local START_UPTIME
  START_UPTIME=$(awk '{print $1}' /proc/uptime)

  local OUTPUT
  OUTPUT=$("$@" 2>&1)
  local RC=$?

  local END_UPTIME
  END_UPTIME=$(awk '{print $1}' /proc/uptime)
  local DURATION
  DURATION=$(awk -v s="$START_UPTIME" -v e="$END_UPTIME" 'BEGIN {
    d = e - s;
    if (d < 0.001) d = 0.001;
    printf "%.3f", d;
  }')

  if [[ "$EXPECT_PASS" == "true" && $RC -eq 0 ]] || [[ "$EXPECT_PASS" == "false" && $RC -ne 0 ]]; then
    echo "[PASS] $NAME (${DURATION}s)"
    TESTCASES_XML+="  <testcase classname=\"validation\" name=\"${NAME}\" time=\"${DURATION}\"/>"$'\n'
  else
    echo "[FAIL] $NAME (${DURATION}s):$OUTPUT" >&2
    FAILURES=$((FAILURES + 1))
    local ESCAPED_OUT
    ESCAPED_OUT=$(echo "$OUTPUT" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g' | tr '\n' ' ')
    TESTCASES_XML+="  <testcase classname=\"validation\" name=\"${NAME}\" time=\"${DURATION}\"><failure message=\"Unexpected exit code ${RC}\">${ESCAPED_OUT}</failure></testcase>"$'\n'
  fi
}

run_case "bash_syntax_check" "true" bash -n scripts/validate_config.sh scripts/rollout_guard.sh scripts/package_lambda.sh lambda/bootstrap consumer/server.sh
run_case "valid_candidate_schema" "true" ./scripts/validate_config.sh config/candidate-valid.yaml
run_case "signed_v1_4_ed25519" "true" ./scripts/validate_config.sh config/candidate-v1.4.yaml config/candidate-v1.4.yaml.sig security/public/ed25519-public.pem
run_case "reject_broken_yaml" "false" ./scripts/validate_config.sh config/candidate-broken.yaml
run_case "reject_oversized_yaml" "false" ./scripts/validate_config.sh config/candidate-oversized.yaml
run_case "reject_bad_semantic_rules" "false" ./scripts/validate_config.sh config/candidate-v1.5-bad.yaml
run_case "reject_duplicate_rule_names" "false" ./scripts/validate_config.sh config/candidate-v1.5-failure.yaml

cat <<XML > "$REPORT_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="blast-radius-bash-suite" tests="${TOTAL}" failures="${FAILURES}">
${TESTCASES_XML}</testsuite>
XML

echo "Generated $REPORT_FILE: $TOTAL tests,$FAILURES failures."
(( FAILURES == 0 ))
