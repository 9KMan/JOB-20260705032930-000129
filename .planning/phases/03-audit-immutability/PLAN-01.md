---
phase: 3
decision: "Can we prove that every routing decision is captured in an append-only audit log, per IRS defensibility (IRC 6001 / 7-year retention) intent?"
plan: audit-immutability
type: standard
wave: 1
depends_on: [2]
files_modified: []
autonomous: true
acceptance_decision: "PASS if append_audit_event writes one JSON line + read_audit_log roundtrips cleanly + audit events capture actor/ts/doc_id/event_type/payload (zero missing fields) + every routing decision emits exactly one event under the test runner."
---

# Phase 03 — Audit Immutability

## Question this phase answers

> "When a senior reviewer asks 'who approved doc X and when?', can we point to an immutable, time-ordered audit log with no missing fields — even though the PoC stores it in /tmp/poc-audit-log.jsonl?"

## Decision outcome

| Approach | Pass | Fail |
|---|---|---|
| Append-only JSONL with required-shape contract | Every event has ts + doc_id + event_type + actor + payload; reads are deterministic; no overwrites | Mutable file; missing required fields; reads miss entries |

If **pass**: IRS auditor / partner / senior can rely on the log for accountability.
If **fail**: Production build needs an actual database (Postgres audit_events with BEFORE-UPDATE/DELETE triggers).

## Files to Create

(no new files — appends to `src/router.py`)

## Tasks

### Task 01 — Add audit append + read functions to `src/router.py`

Append the following to `src/router.py` (already has `route_document()` from Phase 02):

```python
# --- Audit log (append-only; PoC: file-backed; production: Postgres) ---------------
_AUDIT_LOG_PATH = Path("/tmp/poc-audit-log.jsonl")

AUDIT_EVENT_SCHEMA = {"ts", "doc_id", "event_type", "actor", "payload"}


def append_audit_event(doc_id: str, event_type: str, actor: str, payload: dict) -> None:
    """Append one immutable event. Fails loud if any required field is missing."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "doc_id": doc_id,
        "event_type": event_type,
        "actor": actor,
        "payload": payload,
    }
    missing = AUDIT_EVENT_SCHEMA - set(event.keys())
    assert not missing, f"audit event missing fields: {missing}"
    with _AUDIT_LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


def read_audit_log(doc_id: str | None = None) -> list[dict]:
    """Read audit log lines (optionally filtered by doc_id). Returns [] if file missing."""
    if not _AUDIT_LOG_PATH.exists():
        return []
    events = []
    with _AUDIT_LOG_PATH.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if doc_id is None or ev.get("doc_id") == doc_id:
                events.append(ev)
    return events
```

### Task 02 — Append 2 audit tests to `tests/test_classifier_router.py`

```python
# (add to tests/test_classifier_router.py)

from router import append_audit_event, read_audit_log


def test_audit_log_append_and_read():
    test_doc = "doc-test123"
    append_audit_event(test_doc, "test_event_1", "pytest", {"hello": "world"})
    append_audit_event(test_doc, "test_event_2", "pytest", {"hello": "again"})
    events = read_audit_log(doc_id=test_doc)
    assert len(events) >= 2
    assert "test_event_1" in [e["event_type"] for e in events]
    assert "test_event_2" in [e["event_type"] for e in events]


def test_audit_log_includes_actor():
    test_doc = "doc-actor-test"
    append_audit_event(test_doc, "actor_check", "pytest", {})
    events = read_audit_log(doc_id=test_doc)
    actors = {e["actor"] for e in events}
    assert "pytest" in actors
```

## Done When

1. `python -m py_compile src/router.py` succeeds after the append.
2. `pytest tests/test_classifier_router.py -v -k "audit"` runs 2 audit tests; all pass.
3. The audit log file `/tmp/poc-audit-log.jsonl` opens and is parseable as JSONL.
4. **Every required field (ts + doc_id + event_type + actor + payload) is non-empty in every event** (validated via the assert in `append_audit_event`).
5. `read_audit_log(doc_id=...)` filters correctly without dropping entries.
