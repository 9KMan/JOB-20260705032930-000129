---
phase: 4
plan: review-ui
type: standard
wave: 1
depends_on: [1, 2, 3]
files_modified: [src/ui.py]
autonomous: true
requirements:
  - Sidebar summary with route counts
  - Side-by-side raw text + extracted JSON with confidence highlighting
  - One-click Approve / Override (with reason) / DLQ with audit append
---

# Phase 04: Streamlit Reviewer UI

**Goal:** Deliver `src/ui.py` — a Streamlit page showing pipeline summary + senior reviewer queue + side-by-side raw text + extracted JSON with one-click Approve / Override. This is Block D from `.planning/JOB-129-POC-SCOPE.md`.

**Context:** The PoC UI has no auth (production adds OIDC — OUT_OF_SCOPE.md item 7). Run with `streamlit run src/ui.py --server.port=8501`.

## Tasks

### 1. Streamlit page setup + sidebar summary

**Wave:** 1
**Depends on:** Phases 1-3
**Files modified:** `src/ui.py`

<read_first>
- docs/extracted/*.json (output from Phase 3)
- /tmp/poc-audit-log.jsonl (audit log from Phase 2)
- samples/*.txt (so we can re-read raw text)
</read_first>

<action>
Create `src/ui.py`:

1. `import streamlit as st` plus stdlib json / pathlib.Path / datetime.
2. `st.set_page_config(page_title="...", layout="wide")` + `st.title("...")`.
3. Constants: `REPO_ROOT`, `EXTRACTED`, `SAMPLES`, `AUDIT_LOG = Path("/tmp/poc-audit-log.jsonl")`.
4. `st.session_state` defaults for `approved_docs: list[str]` and `overridden_docs: list[dict]`.
5. Sidebar with: pipeline summary metrics (total extracted, decision counts by route) + audit log path.
6. Main: senior_reviewer queue listing using `queue = [d for d in _load_extracted() if d["data"]["routing"]["route"] == "senior_reviewer"]`. If empty, show success message and `st.stop()`.

`_load_extracted()` reads `EXTRACTED/*.json` and returns `[{path, data}]`.

`_load_sample(text_path)` reads the raw text back from the `source_file` field in the extracted JSON.
</action>

<acceptance_criteria>
- `streamlit run src/ui.py --server.port=8501` boots without error
- Sidebar shows route breakdown correctly when at least one sample has been processed
- Empty queue shows the success message
</acceptance_criteria>

### 2. Side-by-side raw + extracted view with confidence highlighting

**Wave:** 1
**Depends on:** Task 1
**Files modified:** `src/ui.py`

<action>
1. Two-column layout (`st.columns(2)`):
   - Left: `st.code(sample_text, language="text")` showing the raw document.
   - Right: Write `doc_type`, `document_id`, `classification_confidence`. Then iterate `extracted["fields"]` and emit `:green[ok]`, `:orange[warn]`, `:red[!!]` based on confidence thresholds (>=0.8 / >=0.6 / <0.6) with the field name + value + confidence.

2. Reading: pulled from `queue[0]` (first item in senior_reviewer queue).
</action>

<acceptance_criteria>
- Side-by-side columns render for the first queue item
- Confidence color highlighting works for all three thresholds
- Sample text reads from the source file referenced in the extracted JSON
</acceptance_criteria>

### 3. Review actions: Approve / Override / DLQ with audit

**Wave:** 1
**Depends on:** Task 2
**Files modified:** `src/ui.py`

<action>
Add an action bar with 3 columns:

1. **Approve** — primary button. Appends `extracted.document_id` to `st.session_state.approved_docs` and writes an audit event with `actor=senior-reviewer-poc, event_type=human_approved, payload={action: approve}`.

2. **Override** — form. For each field, render a text input pre-filled with the current value. Override fields keyed by name with new values. Reason field (required, blocked submit if empty). Appends to `st.session_state.overridden_docs` and writes an audit event with `event_type=human_overridden, actor=senior-reviewer-poc, payload={overrides, reason}`.

3. **DLQ** — destructive button. Writes an audit event with `event_type=human_dlq, payload={action: dlq}`. Does NOT actually move the JSON; the audit log marks it.

After action buttons, show session-state approvals and overrides for traceability.

All audit writes: `with AUDIT_LOG.open("a") as f: f.write(json.dumps({...}) + "\n")`. Same shape as Phase 2's append_audit_event.
</action>

<acceptance_criteria>
- Clicking Approve: appends to session state, appends audit event with type=human_approved
- Submitting Override: requires non-empty reason; appends audit event with type=human_overridden + override payload
- DLQ button: appends audit event with type=human_dlq
- Audit log file shows the action entries when re-read
</acceptance_criteria>

## Verification

```bash
# Set up (already done by demo.sh):
bash scripts/demo.sh

# Launch UI:
PYTHONPATH=src streamlit run src/ui.py --server.port=8501

# In a browser, verify:
# - Sidebar shows "5 Total extracted", "3 preparer queue", "2 senior reviewer"
# - Main panel shows K-1 sample (senior-reviewer routed) side-by-side
# - Approve / Override / DLQ buttons each work and append to /tmp/poc-audit-log.jsonl
```

For automated verification: no pytest here; the runner end-to-end (Phase 3) covers the data side, the UI is purely an inspection/approval layer.

## Out of scope for this phase

- Streamlit auth (OIDC / SSO) — OUT_OF_SCOPE.md item 7
- Email-draft automation — production swap
- Cross-year reconciliation engine — production swap
- Power BI dashboard / partner dashboards — production swap
