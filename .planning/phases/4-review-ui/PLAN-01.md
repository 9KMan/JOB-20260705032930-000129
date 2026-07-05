---
phase: 4
plan: review-ui
type: standard
wave: 1
depends_on: [1, 2, 3]
files_modified: [src/ui.py, tests/test_ui_smoke.py, scripts/run_ui.sh]
autonomous: true
requirements:
  - Sidebar summary with route counts
  - Side-by-side raw text + extracted JSON with confidence highlighting
  - One-click Approve / Override (with reason) / DLQ with audit append
---

# Plan: Streamlit Reviewer UI

## Objective

Deliver a Streamlit review UI (`src/ui.py`) for the CPA document intake PoC. Provides a sidebar pipeline summary, a side-by-side raw-text + extracted-JSON view with confidence highlighting, and one-click Approve / Override (with reason) / DLQ actions that append events to the audit log. Runs locally; deployment notes are out of scope (covered in production plans).

**Block D from `.planning/JOB-129-POC-SCOPE.md`.**

## Files to Create

src/ui.py
tests/test_ui_smoke.py
scripts/run_ui.sh

## Tasks

### Phase 1 — Page setup + sidebar summary

Set `st.set_page_config(layout="wide")`, render sidebar with pipeline metrics (total processed + route counts) loaded from `docs/extracted/*.json` and an audit-log path indicator. Show senior-reviewer queue count in main panel. If queue is empty, render a success message and stop.

Read sidebar from `EXTRACTED.glob("*.json")`. Each file's `data["routing"]["route"]` contributes to the decision_counts dict.

### Phase 2 — Side-by-side raw + extracted view

Two-column layout. Left column shows `st.code(sample_text, language="text")` (the raw text from the source_file referenced in the extracted JSON). Right column shows document type, ID, classification confidence, then iterates `extracted["fields"]` and emits confidence-colored markers (`:green[ok]` ≥ 0.8, `:orange[warn]` ≥ 0.6, `:red[!!]` < 0.6) with field name + value + numeric confidence.

Pick the first item from the senior reviewer queue.

### Phase 3 — Review actions with audit append

3-column action bar:

1. **Approve** — primary button. Append doc_id to `st.session_state.approved_docs` and write one audit event to `/tmp/poc-audit-log.jsonl` with shape `{ts, doc_id, event_type: "human_approved", actor: "senior-reviewer-poc", payload: {action: "approve"}}`.

2. **Override** — `st.form("override_form")` with one text input per field pre-filled with current value, plus a required reason textarea. On submit, write one audit event with `event_type: "human_overridden", payload: {overrides: {...}, reason: "..."}`.

3. **DLQ** — destructive button. Audit event with `event_type: "human_dlq", payload: {action: "dlq"}`.

After action buttons, render session-state approvals and overrides for in-session traceability.

## Done When

1. `streamlit run src/ui.py --server.port=8501` boots without error
2. Sidebar shows correct route breakdown when samples have been processed via `bash scripts/demo.sh`
3. Side-by-side panel renders with confidence-colored field markers
4. Clicking Approve appends one `human_approved` audit event to `/tmp/poc-audit-log.jsonl`
5. Submitting Override (with non-empty reason) appends one `human_overridden` audit event
6. Clicking DLQ appends one `human_dlq` audit event
7. `bash scripts/run_ui.sh` boots the UI in a single command for new users

## Reading Order

```file:src/ui.py
"""Streamlit review UI for the CPA document intake PoC.

Run: streamlit run src/ui.py

Provides:
- Sidebar pipeline summary (total extracted + decision counts by route)
- Senior reviewer queue listing (side-by-side raw text vs extracted JSON)
- Per-field confidence highlighting
- One-click Approve / Override / DLQ actions with audit-log append
- Session-state record of approvals + overrides

This is the PoC UI; production adds:
- OpenID Connect against the firm's Microsoft tenant
- Multi-tenant scoping
- Production audit writes through to Postgres audit_events table
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


def _audit(event_type: str, doc_id: str, payload: dict) -> None:
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "doc_id": doc_id,
            "event_type": event_type,
            "actor": "senior-reviewer-poc",
            "payload": payload,
        }) + "\n")


with st.sidebar:
    st.header("Pipeline summary")
    docs = _load_extracted()
    if not docs:
        st.info("No documents processed yet. Run `python -m src.runner once` first.")
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
        _audit("human_approved", extracted["document_id"], {"action": "approve"})
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
            _audit("human_overridden", extracted["document_id"], entry)
            st.success(f"Overridden {len(overrides)} fields on {extracted['document_id']}")

with cols[2]:
    if st.button("Send to DLQ (irrecoverable)"):
        _audit("human_dlq", extracted["document_id"], {"action": "dlq"})
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

```file:tests/test_ui_smoke.py
"""Smoke test for the Streamlit UI: importable, parses cleanly, key constants present."""
from pathlib import Path
import importlib.util

UI = Path(__file__).parent.parent / "src" / "ui.py"


def test_ui_importable():
    """src/ui.py compiles + imports without errors."""
    spec = importlib.util.spec_from_file_location("ui", UI)
    mod = importlib.util.module_from_spec(spec)
    # Streamlit decorators run on import — that's fine for a smoke check
    spec.loader.exec_module(mod)
    assert hasattr(mod, "_audit")
    assert hasattr(mod, "_load_extracted")


def test_ui_emits_correct_constants():
    """The UI module references the expected repo paths."""
    text = UI.read_text()
    assert "EXTRACTED = REPO_ROOT /" in text
    assert "AUDIT_LOG = Path" in text
    assert "_audit" in text
    assert "human_approved" in text
    assert "human_overridden" in text
    assert "human_dlq" in text
```

```file:scripts/run_ui.sh
#!/usr/bin/env bash
# Boot the Streamlit UI for the PoC.
# First processes the samples (idempotent) so there's data to review, then launches UI.
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/demo.sh  # process the 5 synthetic samples into docs/extracted/
exec streamlit run src/ui.py --server.address=0.0.0.0 --server.port=8501
```
