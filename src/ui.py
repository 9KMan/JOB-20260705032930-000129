"""Streamlit review UI for the CPA PoC.

Run with:
    streamlit run src/ui.py

Provides:
- Side-by-side view of a sample doc + extracted JSON
- Confidence per field with color highlighting
- One-click "Approve" or "Override" workflow (with reason)
- Audit log viewer

PoC only — real build has user auth, document storage backend, and the
audit log writes through to PostgreSQL.
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

# --- State -----------------------------------------------------------

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


def _load_sample(text: Path) -> str:
    """For PoC: show the original text alongside extracted JSON."""
    return text.read_text() if text.exists() else "[no sample text stored]"


# --- Sidebar: routes summary ---------------------------------------

with st.sidebar:
    st.header("Pipeline summary")
    docs = _load_extracted()
    if not docs:
        st.info("No documents processed yet. Run `python -m src.runner once` first.")
    else:
        routes = {}
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

# --- Main: review queue -------------------------------------------

queue = [d for d in _load_extracted() if d["data"]["routing"]["route"] == "senior_reviewer"]

st.subheader(f"Senior reviewer queue ({len(queue)} pending)")
if not queue:
    st.success("Nothing in the queue. Run the runner to ingest more docs.")
    st.stop()

# Pick first item or one selected
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
            color = "green"
            icon = "ok"
        elif c >= 0.6:
            color = "orange"
            icon = "warn"
        else:
            color = "red"
            icon = "!!"
        st.markdown(f"**:{color}[{icon}]** `{field_name}` = `{v}`  (conf={c:.2f})")

# --- Actions ------------------------------------------------------

st.divider()
st.subheader("Review actions")
cols = st.columns(3)
with cols[0]:
    if st.button("Approve as-is", type="primary"):
        st.session_state.approved_docs.append(extracted["document_id"])
        # PoC audit append
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "doc_id": extracted["document_id"],
                "event_type": "human_approved",
                "actor": "senior-reviewer-poc",
                "payload": {"action": "approve", "fields_kept": list(extracted["fields"].keys())},
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

# --- Approved / override trace --------------------------

if st.session_state.approved_docs:
    st.divider()
    st.subheader("Recently approved in this session")
    st.code("\n".join(st.session_state.approved_docs))
if st.session_state.overridden_docs:
    st.divider()
    st.subheader("Recently overridden in this session")
    st.json(st.session_state.overridden_docs)
