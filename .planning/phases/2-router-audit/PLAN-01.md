---
phase: 2
plan: router-audit
type: standard
wave: 1
depends_on: [1]
files_modified: [src/router.py, tests/test_classifier_router.py]
autonomous: true
requirements:
  - rule-based router with confidence-based demotion to senior reviewer
  - default rule table covering W-2/1099-DIV/1099-INT/1099-B -> preparer
  - K-1 / engagement / organizer / unknown -> senior reviewer by default
  - append-only audit log: every routing decision writes one event
  - audit event shape: ts, doc_id, event_type, actor, payload
---

# Phase 02: Router + Audit Log

**Goal:** Deliver `src/router.py` with rule-based routing, confidence-demotion logic, and an append-only audit log. This is Block B from `.planning/JOB-129-POC-SCOPE.md`.

**Context:** Builds on Phase 1 (ExtractedDocument dataclass). Produces RoutingDecision + audit events that Phase 3 (intake worker) will write.

## Tasks

### 1. Route enum + RoutingRule dataclass + DEFAULT_RULES

**Wave:** 1
**Depends on:** —
**Files modified:** `src/router.py`

<action>
Create `src/router.py` with:

1. `from __future__ import annotations`
2. Imports: `json, dataclasses (asdict, dataclass, field), datetime (datetime, timezone), enum (Enum), pathlib (Path)` + `from document_classifier import DocType, ExtractedDocument, ExtractedField`
3. `class Route(str, Enum):` with PREPARER_QUEUE, SENIOR_REVIEWER, DEAD_LETTER, DUPLICATE
4. `@dataclass class RoutingRule:` with `(doc_type: DocType, condition: str | None, route: Route, reason: str)`
5. Module-level `DEFAULT_RULES: list[RoutingRule]` covering: W-2/1099-DIV/1099-INT/1099-B → PREPARER_QUEUE; K-1/ENGAGEMENT_LETTER/ORGANIZER/UNKNOWN → SENIOR_REVIEWER; each with a one-line `reason` (e.g. "W-2 always to preparer queue (high-volume, low-risk)").
</action>

<acceptance_criteria>
- File compiles with `python -m py_compile`
- All 4 Route values present
- 8 RoutingRule entries in DEFAULT_RULES
</acceptance_criteria>

### 2. route_document() with confidence demotion

**Wave:** 1
**Depends on:** Task 1
**Files modified:** `src/router.py`

<read_first>
- src/document_classifier.py (ExtractedDocument schema)
- SPEC.md Section 2 Functional Requirements (routing requirements)
- samples/*.txt (to test routing decisions)
</read_first>

<action>
Implement:

1. `@dataclass class RoutingDecision:` with `(document_id, route, rule_matched, classification_confidence, avg_field_confidence, flagged_fields: list[str] = field(...), decided_at: str = field(default_factory=now_iso), decided_by: str = "poc-router-v0")` plus `to_dict()` that converts enums.

2. Helper `_avg_confidence(fields) -> float` — mean of `field.confidence` for all fields; 0.0 for empty.

3. Helper `_flagged_fields(fields, threshold=0.7) -> list[str]` — names of fields with confidence < threshold.

4. `route_document(doc, rules=None) -> RoutingDecision`:
   - Use DEFAULT_RULES if rules not given.
   - Iterate rules in order, take first matching `doc_type`. Default = SENIOR_REVIEWER.
   - Override to SENIOR_REVIEWER if classification_confidence < 0.5 (could be misclassified).
   - Override to SENIOR_REVIEWER if classification_confidence in (0.5, 0.65) AND current route is PREPARER_QUEUE (safety demotion).
   - DO NOT demote on classification in (0.65, 0.8) — default rule already encodes intent.
   - Override to SENIOR_REVIEWER if any field has confidence < 0.7 AND current route is PREPARER_QUEUE.
   - `rule_matched` should be the reason string from the rule that triggered the route (or the override reason).

5. The function must be **pure** — same ExtractedDocument always yields the same RoutingDecision (idempotent test passes).
</action>

<acceptance_criteria>
- High-confidence W-2 sample → Route.PREPARER_QUEUE
- K-1 sample → Route.SENIOR_REVIEWER (default rule)
- Unknown sample → Route.SENIOR_REVIEWER
- Forcing field confidence < 0.7 on a preparer-routed doc demotes to senior_reviewer with the field name in flagged_fields
- Routing two identical extracted documents yields identical decision (same route, same flagged_fields, same rule_matched)
- Custom rules argument takes precedence over DEFAULT_RULES
</acceptance_criteria>

### 3. Audit append + read

**Wave:** 1
**Depends on:** —
**Files modified:** `src/router.py`

<action>
Implement:

1. Module-level `_AUDIT_LOG_PATH = Path("/tmp/poc-audit-log.jsonl")` with comment explaining it swaps to Postgres in production.

2. `append_audit_event(doc_id, event_type, actor, payload) -> None`: open file in append mode, write one JSON line with `{ts, doc_id, event_type, actor, payload}`. No flush of other writers; concurrent-safe enough for the PoC.

3. `read_audit_log(doc_id=None) -> list[dict]`: read the file line by line, JSON-load each, filter to doc_id if given. Returns empty list if file doesn't exist. Skip lines that fail to parse.

The audit log is intentionally simple for the PoC; production swaps to Postgres `audit_events` (append-only with BEFORE-UPDATE/DELETE triggers) per OUT_OF_SCOPE.md.
</action>

<acceptance_criteria>
- `append_audit_event("doc-test", "evt", "actor", {"k": "v"})` then `read_audit_log("doc-test")` returns >= 1 event matching the appended data
- `read_audit_log()` on a missing file returns `[]`
- Every event in the log carries actor + ts + doc_id + event_type + payload
</acceptance_criteria>

### 4. Pytest: 8 routing + audit tests

**Wave:** 1
**Depends on:** Tasks 1-3
**Files modified:** `tests/test_classifier_router.py`

<action>
Append these 8 tests to `tests/test_classifier_router.py` (after the Phase 1 tests). Each must follow the existing import pattern (`sys.path.insert(0, ... / "src")`).

Tests to add:

1. `test_route_w2_to_preparer_when_confidence_high` — natural W-2 sample routes to preparer.
2. `test_route_k1_to_senior_reviewer_by_default` — K-1 sample routes to senior.
3. `test_route_unknown_to_senior_reviewer` — Unknown sample to senior.
4. `test_route_demotes_to_senior_when_field_confidence_low` — manually set `e.fields["box1_wages"].confidence = 0.3` then assert route == senior_reviewer and "box1_wages" in flagged_fields.
5. `test_route_is_idempotent` — two extract_document calls on same text produce identical RoutingDecisions.
6. `test_route_with_custom_rule_table` — RoutingRule(DocType.W2, None, Route.SENIOR_REVIEWER, ...) demotes W-2 in the test.
7. `test_audit_log_append_and_read` — append two events for `doc-test123` then read returns both event_types.
8. `test_audit_log_includes_actor` — append for `doc-actor-test`, read, assert "pytest" in actors.
</action>

<acceptance_criteria>
- `pytest tests/test_classifier_router.py -v` runs 18 tests in this file (10 from Phase 1 + 8 here) — all pass
</acceptance_criteria>

## Verification

```bash
PYTHONPATH=src pytest tests/test_classifier_router.py -v
# Expect: 18 passed, 0 failed
```

## Out of scope for this phase

- Postgres-backed audit-events table — OUT_OF_SCOPE.md item 6
- LLM-based exception router — OUT_OF_SCOPE.md item 9
- YAML-loaded rules table — production swap
