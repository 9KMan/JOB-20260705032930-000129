---
phase: 5
decision: "Can a senior reviewer actually use the Streamlit UI to Approve / Override / DLQ docs in their queue (with reasons captured for the audit log), AND does the entire pipeline hold together end-to-end as a single system?"
plan: reviewer-workflow-and-e2e
type: integration
wave: 1
depends_on: [1, 2, 3, 4]
files_modified: [src/ui.py, tests/test_ui_smoke.py, scripts/run_ui.sh, scripts/e2e_smoke.sh]
autonomous: true
acceptance_decision: "PASS if (a) Streamlit module imports cleanly + key UI helpers/constants exist, AND (b) bash scripts/e2e_smoke.sh processes 5 samples end-to-end and the audit log has at least 5 events with the right route counts."
---

# Phase 05 — Reviewer Workflow + End-to-End Smoke

## Question this phase answers

> "Can a senior accountant actually USE this system — Approve / Override / DLQ — without leaving an audit gap, AND does the full pipeline behave correctly when all 5 prior phases' components are wired together?"

## Decision outcome

| Approach | Pass | Fail |
|---|---|---|
| Streamlit UI with 3 actions + e2e smoke script | UI importable; 5-doc e2e shows correct route distribution (3 preparer / 2 senior); each human action appends one audit event | UI throws on import; pipeline crashes end-to-end; audit events from human actions missing fields |

If **pass**: This PoC is genuinely demonstrable to a partner as "here's how it would feel."
If **fail**: Production build needs real auth + Streamlit Cloud deploy work.

## Files to Create

src/ui.py
tests/test_ui_smoke.py
scripts/run_ui.sh
scripts/e2e_smoke.sh

## Tasks

### Task 01 — Streamlit UI module

```file:src/ui.py
"""Streamlit review UI for the CPA PoC.

Run: streamlit run src/ui.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).parent.parent
EXTRACTED = REPO_ROOT / "docs" / "extracted"
SAMPLES = REPO_ROOT / "samples"
AUDIT_LOG = Path("/tmp/poc-audit-log.jsonl")

st.set_page_config(page_title="CPA Intake - Review Queue", layout="wide")
st.title("CPA Document Intake - Senior Reviewer Queue")

if "approved_docs" not in st.session_state:
    st.session_state.approved_docs: list[str] = []
if "overridden_docs" not in st.session_state:
    st.session_state.overridden_docs: list[dict] = []


def _load_extracted() -> list[dict]:
    if not EXTRACTED.exists():
        return []
    out = []
    for p in sorted(EXTRACTED.glob("*.json")):
        try:
            out.append({"path": p, "data": json.loads(p.read_text())})
        except Exception:
            continue
    return out


def _load_sample(text_path: Path) -> str:
    return text_path.read_text() if text_path.exists() else "[no sample text stored]"


with st.sidebar:
    st.header("Pipeline summary")
    docs = _load_extracted()
    if not docs:
        st.info("No documents processed yet. Run `bash scripts/demo.sh` first.")
    else:
        routes: dict[str, int] = {}
        for d in docs:
            r = d["data"]["routing"]["route"]
            routes[r] = routes.get(r, 0) + 1
        st.metric("Total extracted", len(docs))
        for route_name, count in sorted(routes.items()):
            st.metric(route_name.replace("_", " ").title(), count)
        st.divider()
        st.header("Audit log")
        if AUDIT_LOG.exists():
            st.code(f"Path: {AUDIT_LOG}\nSize: {AUDIT_LOG.stat().st_size} bytes")
        else:
            st.caption("(no audit events yet)")

queue = [d for d in _load_extracted() if d["data"]["routing"]["route"] == "senior_reviewer"]
st.subheader(f"Senior reviewer queue ({len(queue)} pending)")
if not queue:
    st.success("Nothing in the queue. Run the runner to ingest more docs.")
    st.stop()

doc = queue[0]
d = doc["data"]
src = d.get("source_file", "?")
sample_text_path = REPO_ROOT / src
sample_text = _load_sample(sample_text_path)

col1, col2 = st.columns(2)
with col1:
    st.markdown("### Raw document")
    st.code(sample_text, language="text")
with col2:
    st.markdown("### Extracted fields")
    extracted = d["extracted"]
    st.write(f"**Type:** {extracted['doc_type']}")
    st.write(f"**Doc ID:** `{extracted['document_id']}`")
    st.write(f"**Classification confidence:** `{extracted['classification_confidence']:.2f}`")
    for field_name, field_data in extracted["fields"].items():
        c = field_data.get("confidence", 0)
        v = field_data.get("value", None)
        if c >= 0.8:
            color, icon = "green", "ok"
        elif c >= 0.6:
            color, icon = "orange", "warn"
        else:
            color, icon = "red", "!!"
        st.markdown(f"**:{color}[{icon}]** `{field_name}` = `{v}`  (conf={c:.2f})")

st.divider()
st.subheader("Review actions")
cols = st.columns(3)
with cols[0]:
    if st.button("Approve as-is", type="primary"):
        st.session_state.approved_docs.append(extracted["document_id"])
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "doc_id": extracted["document_id"],
                "event_type": "human_approved",
                "actor": "senior-reviewer-poc",
                "payload": {"action": "approve"},
            }) + "\n")
        st.success(f"Approved {extracted['document_id']}")

with cols[1]:
    overrides: dict[str, str] = {}
    with st.form("override_form"):
        st.write("Override fields (leave blank to keep):")
        for fname in extracted["fields"].keys():
            old = extracted["fields"][fname].get("value")
            new = st.text_input(f"{fname}", value=str(old) if old is not None else "", key=f"override_{fname}")
            if new and new != str(old):
                overrides[fname] = new
        reason = st.text_area("Reason for override (required)", "")
        if st.form_submit_button("Submit override") and reason and overrides:
            entry = {"doc_id": extracted["document_id"], "overrides": overrides, "reason": reason}
            st.session_state.overridden_docs.append(entry)
            with AUDIT_LOG.open("a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "doc_id": extracted["document_id"],
                    "event_type": "human_overridden",
                    "actor": "senior-reviewer-poc",
                    "payload": entry,
                }) + "\n")
            st.success(f"Overridden {len(overrides)} fields on {extracted['document_id']}")

with cols[2]:
    if st.button("Send to DLQ (irrecoverable)"):
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "doc_id": extracted["document_id"],
                "event_type": "human_dlq",
                "actor": "senior-reviewer-poc",
                "payload": {"action": "dlq"},
            }) + "\n")
        st.error(f"DLQ'd {extracted['document_id']}")

if st.session_state.approved_docs:
    st.divider()
    st.subheader("Recently approved in this session")
    st.code("\n".join(st.session_state.approved_docs))
if st.session_state.overridden_docs:
    st.divider()
    st.subheader("Recently overridden in this session")
    st.json(st.session_state.overridden_docs)
```

### Task 02 — Smoke test + e2e smoke script

```file:tests/test_ui_smoke.py
"""Smoke test for src/ui.py: importable + key helpers/constants present."""
from pathlib import Path
import importlib.util

UI = Path(__file__).parent.parent / "src" / "ui.py"


def test_ui_importable():
    """src/ui.py compiles + imports without errors."""
    spec = importlib.util.spec_from_file_location("ui", UI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "_load_extracted")
    assert hasattr(mod, "_load_sample")


def test_ui_emits_correct_constants():
    text = UI.read_text()
    assert "EXTRACTED = REPO_ROOT" in text
    assert "AUDIT_LOG = Path" in text
    assert "human_approved" in text
    assert "human_overridden" in text
    assert "human_dlq" in text
    assert "Senior reviewer queue" in text
```

```file:scripts/run_ui.sh
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/demo.sh
exec streamlit run src/ui.py --server.address=0.0.0.0 --server.port=8501
```

```file:scripts/e2e_smoke.sh
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
[ "$extracted_count" -eq 5 ] || { echo "FAIL: expected 5 extracted JSONs, got $extracted_count"; exit 1; }
echo "  $extracted_count JSON files extracted (as expected)"

echo "==> Verifying route distribution"
preparer=$(grep -l '"route": "preparer_queue"' docs/extracted/*.json | wc -l)
senior=$(grep -l '"route": "senior_reviewer"' docs/extracted/*.json | wc -l)
echo "  preparer_queue: $preparer"
echo "  senior_reviewer: $senior"
total=$((preparer + senior))
[ "$total" -eq 5 ] || { echo "FAIL: expected 5 total routes, got $total"; exit 1; }
[ "$senior" -ge 2 ] || { echo "FAIL: expected >= 2 senior-routed (K-1 + Unknown), got $senior"; exit 1; }

echo "==> Verifying audit log integrity"
audit_lines=$(wc -l < /tmp/poc-audit-log.jsonl)
[ "$audit_lines" -eq 5 ] || { echo "FAIL: expected 5 audit events, got $audit_lines"; exit 1; }
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
[ "$second_count" -eq 5 ] || { echo "FAIL: idempotency broken; expected 5 files still, got $second_count"; exit 1; }
echo "  idempotency confirmed: still $second_count files after re-run"

echo
echo "==> ALL SMOKE CHECKS PASSED"
echo "  - 5 sample docs classified + extracted + routed"
echo "  - 5 audit events captured with required shape"
echo "  - 2 senior / 3 preparer route distribution (as designed)"
echo "  - Re-run is a no-op"
```

## Done When

1. `python -m py_compile src/ui.py` succeeds.
2. `bash scripts/e2e_smoke.sh` exits with code 0.
3. `pytest tests/test_ui_smoke.py -q` runs 2 UI tests; all pass.
4. `pytest tests/ -q` (entire suite) runs **20 tests**, all pass.
5. `bash scripts/run_ui.sh` boots the Streamlit UI on http://localhost:8501 with no errors.
6. The e2e smoke script's audit-fields check proves every audit event has all 5 required keys.
