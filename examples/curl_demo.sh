#!/usr/bin/env sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API_KEY_HEADER=""
if [ -n "${RAR_API_KEY:-}" ]; then
  API_KEY_HEADER="X-API-Key: ${RAR_API_KEY}"
fi

post_json() {
  if [ -n "$API_KEY_HEADER" ]; then
    curl --fail-with-body --silent --show-error \
      -H "$API_KEY_HEADER" -H 'Content-Type: application/json' "$@"
  else
    curl --fail-with-body --silent --show-error \
      -H 'Content-Type: application/json' "$@"
  fi
}

get_json() {
  if [ -n "$API_KEY_HEADER" ]; then
    curl --fail-with-body --silent --show-error -H "$API_KEY_HEADER" "$@"
  else
    curl --fail-with-body --silent --show-error "$@"
  fi
}

RUN_JSON=$(post_json \
  -H 'Idempotency-Key: refund-curl-demo' \
  --data @examples/retail_refund_plan.json \
  "$BASE_URL/api/v1/runs")
RUN_ID=$(printf '%s' "$RUN_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

echo "created run: $RUN_ID"
post_json -X POST "$BASE_URL/api/v1/runs/$RUN_ID/execute" >/dev/null

APPROVAL_JSON=$(get_json "$BASE_URL/api/v1/runs/$RUN_ID/approvals")
APPROVAL_ID=$(printf '%s' "$APPROVAL_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')

echo "approving: $APPROVAL_ID"
post_json -X POST \
  --data '{"decision":"approve","actor":"demo-manager","reason":"policy checked"}' \
  "$BASE_URL/api/v1/approvals/$APPROVAL_ID/decision" >/dev/null

post_json -X POST "$BASE_URL/api/v1/runs/$RUN_ID/execute"
echo
