#!/usr/bin/env bash
# One isolated runner's fetch of the due prospective window (V2D DATA-ONLY).
#
# Usage: m3e_fetch_window.sh <plan-dir> <staging-dir> <runner-label a|b>
#
# The network boundary of the whole update mechanism lives in the single curl
# below. Every request parameter — endpoint, granularity, user agent, size cap,
# per-window start/end/filename — comes from the offline-emitted curl plan
# (derived from the committed, hash-bound update plan); no host or query literal
# lives in this script or in the workflow YAML. The response bodies are then
# strictly verified OFFLINE (eth_research.m3e.acquire_runner verify) into the
# m3d-format receipt. Failures are hard stops; nothing is retried into ambiguity.
set -euo pipefail

PLAN_DIR="$1"
STAGING="$2"
LABEL="$3"
case "$LABEL" in a | b) ;; *) echo "runner label must be a or b" >&2; exit 1 ;; esac

PLAN="$PLAN_DIR/update_plan.json"
AS_OF="$(cat "$PLAN_DIR/as_of.txt")"
mkdir -p "$STAGING"
cp "$PLAN" "$STAGING/update_plan.json"

uv run --no-sync python -m eth_research.m3e.acquire_runner emit-plan \
  --plan "$PLAN" --out "$STAGING/_curl_plan.json"

ENDPOINT="$(uv run --no-sync python -c 'import json,sys; print(json.load(open(sys.argv[1]))["endpoint"])' "$STAGING/_curl_plan.json")"
GRANULARITY="$(uv run --no-sync python -c 'import json,sys; print(json.load(open(sys.argv[1]))["granularity_seconds"])' "$STAGING/_curl_plan.json")"
USER_AGENT="$(uv run --no-sync python -c 'import json,sys; print(json.load(open(sys.argv[1]))["user_agent"])' "$STAGING/_curl_plan.json")"
MAX_BYTES="$(uv run --no-sync python -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_body_bytes"])' "$STAGING/_curl_plan.json")"

: > "$STAGING/_responses.jsonl"
uv run --no-sync python -c '
import json, sys
for w in json.load(open(sys.argv[1]))["windows"]:
    print(json.dumps([w["ordinal"], w["start_param"], w["end_param"], w["filename"]]))
' "$STAGING/_curl_plan.json" | while IFS= read -r line; do
  ORDINAL="$(printf '%s' "$line" | uv run --no-sync python -c 'import json,sys; print(json.load(sys.stdin)[0])')"
  START="$(printf '%s' "$line" | uv run --no-sync python -c 'import json,sys; print(json.load(sys.stdin)[1])')"
  END="$(printf '%s' "$line" | uv run --no-sync python -c 'import json,sys; print(json.load(sys.stdin)[2])')"
  FILENAME="$(printf '%s' "$line" | uv run --no-sync python -c 'import json,sys; print(json.load(sys.stdin)[3])')"
  RETRIEVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  HEADERS="$STAGING/_headers_$ORDINAL.txt"
  HTTP_CODE="$(curl --proto '=https' --tlsv1.2 --max-redirs 0 --fail --silent --show-error \
    --max-filesize "$MAX_BYTES" --max-time 60 \
    -H "User-Agent: $USER_AGENT" \
    -D "$HEADERS" \
    -o "$STAGING/$FILENAME" \
    -w '%{http_code}' \
    --get "$ENDPOINT" \
    --data-urlencode "granularity=$GRANULARITY" \
    --data-urlencode "start=$START" \
    --data-urlencode "end=$END")"
  CONTENT_TYPE="$(tr -d '\r' < "$HEADERS" | awk 'tolower($1)=="content-type:" {sub(/^[^:]*: */, ""); print; exit}')"
  rm -f "$HEADERS"
  uv run --no-sync python -c '
import json, sys
print(json.dumps({
    "ordinal": int(sys.argv[1]),
    "filename": sys.argv[2],
    "http_code": int(sys.argv[3]),
    "retrieved_at": sys.argv[4],
    "content_type": sys.argv[5],
}, sort_keys=True))
' "$ORDINAL" "$FILENAME" "$HTTP_CODE" "$RETRIEVED_AT" "$CONTENT_TYPE" >> "$STAGING/_responses.jsonl"
done

FIRST="$(uv run --no-sync python -c 'import json,sys; print(json.load(open(sys.argv[1]))["first_missing_open"][:10].replace("-",""))' "$PLAN")"
LAST="$(uv run --no-sync python -c 'import json,sys; d=json.load(open(sys.argv[1])); import datetime; e=d["completed_day_exclusive_end"]; print(e[:10].replace("-",""))' "$PLAN")"
KEY16="$(uv run --no-sync python -c 'import json,sys; print(json.load(open(sys.argv[1]))["idempotency_key"][:16])' "$PLAN")"

uv run --no-sync python -m eth_research.m3e.acquire_runner verify \
  --plan "$PLAN" \
  --staging "$STAGING" \
  --receipt-out "$STAGING/acquisition_receipt.json" \
  --attempt-id "coinbase-eth-usd-prospective-update-runner-$LABEL" \
  --workflow-run-id "${GITHUB_RUN_ID:-local}" \
  --source-commit "${GITHUB_SHA:-0000000000000000000000000000000000000000}" \
  --client-identity "curl-hardened" \
  --runner-identity "github-hosted-runner-$LABEL-${GITHUB_RUN_ID:-local}" \
  --created-at "$AS_OF"

rm -f "$STAGING/_curl_plan.json" "$STAGING/_responses.jsonl"
echo "runner $LABEL: window $FIRST..$LAST key $KEY16 verified"
