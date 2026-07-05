#!/usr/bin/env bash
# Boot the Streamlit UI for the PoC.
# First processes the samples (idempotent) so there's data to review, then launches UI.
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/demo.sh  # process the 5 synthetic samples into docs/extracted/
exec streamlit run src/ui.py --server.address=0.0.0.0 --server.port=8501
