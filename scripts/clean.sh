#!/usr/bin/env bash
# Clean the PoC state (extracted JSONs + dlq + audit log).
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf docs/extracted/* docs/dlq/* /tmp/poc-audit-log.jsonl
echo "Cleaned."
