#!/usr/bin/env bash
# Run pytest + regenerate diagrams + run demo.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHONPATH=src pytest tests/ "$@"
