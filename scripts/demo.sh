#!/usr/bin/env bash
# Demo helper — drops all synthetic samples into inbox and runs the runner.
# Use this to verify the system end-to-end on a clean checkout.
set -euo pipefail

cd "$(dirname "$0")/.."

# Reset
rm -rf docs/extracted/* docs/dlq/* /tmp/poc-audit-log.jsonl
cp samples/*.txt docs/inbox/

echo "==> Running intake (PoC runner)"
PYTHONPATH=src python3 -m src.runner once

echo
echo "==> Idempotency check (re-run should skip everything)"
PYTHONPATH=src python3 -m src.runner once

echo
echo "==> Listing extracted docs and audit log tail"
ls -1 docs/extracted/
echo
echo "Audit events: $(wc -l < /tmp/poc-audit-log.jsonl)"
echo
echo "==> To launch the UI:"
echo "  PYTHONPATH=src streamlit run src/ui.py --server.port=8501"
