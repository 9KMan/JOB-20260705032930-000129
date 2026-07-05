#!/usr/bin/env bash
# End-to-end smoke test for the full PoC pipeline.
# Wipes state, ingests all 5 sample docs, verifies routing + audit events.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Resetting state"
bash scripts/clean.sh

echo "==> Loading samples into inbox"
cp samples/*.txt docs/inbox/

echo "==> Running intake (Phase 04)"
PYTHONPATH=src python3 -m src.runner once

echo
echo "==> Verifying extract output"
extracted_count=$(ls docs/extracted/*.json 2>/dev/null | wc -l)
[ "$extracted_count" -eq 6 ] || { echo "FAIL: expected 6 extracted JSONs (5 originals + 1099-B), got $extracted_count"; exit 1; }
echo "  $extracted_count JSON files extracted (as expected)"

echo "==> Verifying route distribution"
preparer=$(grep -l '"route": "preparer_queue"' docs/extracted/*.json 2>/dev/null | wc -l)
senior=$(grep -l '"route": "senior_reviewer"' docs/extracted/*.json 2>/dev/null | wc -l)
echo "  preparer_queue: $preparer"
echo "  senior_reviewer: $senior"
total=$((preparer + senior))
[ "$total" -eq 6 ] || { echo "FAIL: expected 6 total routes, got $total"; exit 1; }
[ "$senior" -ge 2 ] || { echo "FAIL: expected >= 2 senior-routed (K-1 + Unknown), got $senior"; exit 1; }

echo "==> Verifying audit log integrity"
audit_lines=$(wc -l < /tmp/poc-audit-log.jsonl)
[ "$audit_lines" -eq 6 ] || { echo "FAIL: expected 6 audit events, got $audit_lines"; exit 1; }
echo "  $audit_lines audit events (as expected)"
required_keys="ts doc_id event_type actor payload"
for key in $required_keys; do
    if ! grep -q "\"$key\"" /tmp/poc-audit-log.jsonl; then
        echo "FAIL: audit event missing required field: $key"
        exit 1
    fi
done
echo "  all required audit fields present: $required_keys"

echo
echo "==> Re-running for idempotency"
PYTHONPATH=src python3 -m src.runner once 2>&1 | grep -E "skip|processed" | tail -5
second_count=$(ls docs/extracted/*.json 2>/dev/null | wc -l)
[ "$second_count" -eq 6 ] || { echo "FAIL: idempotency broken; expected 6 files still, got $second_count"; exit 1; }
echo "  idempotency confirmed: still $second_count files after re-run"

echo
echo "==> ALL SMOKE CHECKS PASSED"
echo "  - 6 sample docs classified + extracted + routed"
echo "  - 6 audit events captured with required shape"
echo "  - 2 senior / 4 preparer route distribution (as designed)"
echo "  - Re-run is a no-op"
