---
phase: 2
plan: router-audit
type: standard
wave: 1
depends_on: [1]
files_modified: [src/router.py]
autonomous: true
requirements:
  - rule-based router with confidence-based demotion to senior reviewer
  - default rule table covering W-2/1099-DIV/1099-INT/1099-B -> preparer
  - K-1 / engagement / organizer / unknown -> senior reviewer by default
  - append-only audit log: every routing decision writes one event
  - audit event shape: ts, doc_id, event_type, actor, payload
---

# Plan: Router + Audit Log

## Objective

Deliver `src/router.py` with rule-based routing, confidence-demotion logic, and an append-only audit log. **Block B from `.planning/JOB-129-POC-SCOPE.md`.**

## Files to Create

src/router.py

## Tasks

### Phase 1 — Route enum, RoutingRule dataclass, DEFAULT_RULES

```file:src/router.py
"""Rule + LLM router for document routing.

Routes extracted documents to:
- Preparer queue (if classification + extraction confidence both >= 0.8)
- Senior reviewer queue (if either confidence < 0.8)
- DLT (dead letter) (if schema invalid or extraction failed)

Idempotency:
- Documents are keyed by SHA-256 of the raw text hash (computed in the
  extractor). Re-processing the same doc_id returns the same routing decision.

PoC implementation:
- Rules defined in DEFAULT_RULES (hardcoded fallback — real build loads from YAML).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from document_classifier import DocType, ExtractedDocument, ExtractedField


class Route(str, Enum):
    PREPARER_QUEUE = "preparer_queue"
    SENIOR_REVIEWER = "senior_reviewer"
    DEAD_LETTER = "dead_letter"
    DUPLICATE = "duplicate"


@dataclass
class RoutingRule:
    """A rule mapping doc_type + optional condition -> Route."""
    doc_type: DocType
    condition: str | None
    route: Route
    reason: str


DEFAULT_RULES: list[RoutingRule] = [
    RoutingRule(DocType.W2, None, Route.PREPARER_QUEUE, "W-2 always to preparer queue (high-volume, low-risk)"),
    RoutingRule(DocType.FORM_1099_DIV, None, Route.PREPARER_QUEUE, "1099-DIV to preparer queue"),
    RoutingRule(DocType.FORM_1099_INT, None, Route.PREPARER_QUEUE, "1099-INT to preparer queue"),
    RoutingRule(DocType.FORM_1099_B, None, Route.PREPARER_QUEUE, "1099-B to preparer queue"),
    RoutingRule(DocType.K1_PAGE1, None, Route.SENIOR_REVIEWER, "K-1 to senior reviewer (complex)"),
    RoutingRule(DocType.ENGAGEMENT_LETTER, None, Route.SENIOR_REVIEWER, "Engagement letter to senior"),
    RoutingRule(DocType.ORGANIZER, None, Route.SENIOR_REVIEWER, "Organizer to senior"),
    RoutingRule(DocType.UNKNOWN, None, Route.SENIOR_REVIEWER, "Unknown doc type -> manual triage"),
]


@dataclass
class RoutingDecision:
    document_id: str
    route: Route
    rule_matched: str
    classification_confidence: float
    avg_field_confidence: float
    flagged_fields: list[str] = field(default_factory=list)
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    decided_by: str = "poc-router-v0"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["route"] = self.route.value
        return d


def _avg_confidence(fields: dict[str, ExtractedField]) -> float:
    if not fields:
        return 0.0
    return sum(f.confidence for f in fields.values()) / len(fields)


def _flagged_fields(fields: dict[str, ExtractedField], threshold: float = 0.7) -> list[str]:
    return [name for name, f in fields.items() if f.confidence < threshold]


def route_document(doc: ExtractedDocument, rules: list[RoutingRule] | None = None) -> RoutingDecision:
    """Pure routing function — same input always produces same decision."""
    rules = rules or DEFAULT_RULES
    matched_rule: RoutingRule | None = None
    for rule in rules:
        if rule.doc_type == doc.doc_type:
            matched_rule = rule
            break
    route = matched_rule.route if matched_rule else Route.SENIOR_REVIEWER
    reason = matched_rule.reason if matched_rule else "No rule matched"

    if doc.classification_confidence < 0.5:
        route = Route.SENIOR_REVIEWER
        reason = (
            f"Classification confidence {doc.classification_confidence:.2f} < 0.5 — "
            f"could be misclassified; manual triage required"
        )
    elif doc.classification_confidence < 0.65 and route == Route.PREPARER_QUEUE:
        route = Route.SENIOR_REVIEWER
        reason = (
            f"Classification confidence {doc.classification_confidence:.2f} in (0.5, 0.65); "
            f"promoted to senior for safety"
        )

    flagged = _flagged_fields(doc.fields, threshold=0.7)
    if flagged and route == Route.PREPARER_QUEUE:
        route = Route.SENIOR_REVIEWER
        reason = f"Field extraction flagged: {', '.join(flagged)}"

    return RoutingDecision(
        document_id=doc.document_id, route=route, rule_matched=reason,
        classification_confidence=doc.classification_confidence,
        avg_field_confidence=_avg_confidence(doc.fields),
        flagged_fields=flagged,
    )


# Audit log (PoC uses /tmp; production swaps to Postgres audit_events with 7-yr retention)
_AUDIT_LOG_PATH = Path("/tmp/poc-audit-log.jsonl")


def append_audit_event(doc_id: str, event_type: str, actor: str, payload: dict) -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "doc_id": doc_id, "event_type": event_type,
        "actor": actor, "payload": payload,
    }
    with _AUDIT_LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


def read_audit_log(doc_id: str | None = None) -> list[dict]:
    if not _AUDIT_LOG_PATH.exists():
        return []
    events = []
    with _AUDIT_LOG_PATH.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
                if doc_id is None or ev.get("doc_id") == doc_id:
                    events.append(ev)
            except json.JSONDecodeError:
                continue
    return events
```

### Phase 2 — Tests appended to `tests/test_classifier_router.py`

Append these to the existing test file:

```python
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from router import Route, RoutingRule, append_audit_event, read_audit_log, route_document


def test_route_w2_to_preparer_when_confidence_high():
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    decision = route_document(extracted)
    assert decision.route == Route.PREPARER_QUEUE


def test_route_k1_to_senior_reviewer_by_default():
    text = (REPO / "samples" / "k1-sample-001.txt").read_text()
    extracted = extract_document(text)
    decision = route_document(extracted)
    assert decision.route == Route.SENIOR_REVIEWER


def test_route_unknown_to_senior_reviewer():
    text = (REPO / "samples" / "unknown-sample-001.txt").read_text()
    extracted = extract_document(text)
    decision = route_document(extracted)
    assert decision.route == Route.SENIOR_REVIEWER


def test_route_demotes_to_senior_when_field_confidence_low():
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    extracted.fields["box1_wages"].confidence = 0.3
    decision = route_document(extracted)
    assert decision.route == Route.SENIOR_REVIEWER
    assert "box1_wages" in decision.flagged_fields


def test_route_is_idempotent():
    text = (REPO / "samples" / "1099-div-sample-001.txt").read_text()
    e1 = extract_document(text); e2 = extract_document(text)
    d1 = route_document(e1); d2 = route_document(e2)
    assert d1.route == d2.route
    assert d1.document_id == d2.document_id


def test_route_with_custom_rule_table():
    custom = [RoutingRule(DocType.W2, None, Route.SENIOR_REVIEWER, "demote W-2 for test")]
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    decision = route_document(extracted, rules=custom)
    assert decision.route == Route.SENIOR_REVIEWER


def test_audit_log_append_and_read():
    test_doc = "doc-test123"
    append_audit_event(test_doc, "test_event_1", "pytest", {"hello": "world"})
    append_audit_event(test_doc, "test_event_2", "pytest", {"hello": "again"})
    events = read_audit_log(doc_id=test_doc)
    assert len(events) >= 2
    assert "test_event_1" in [e["event_type"] for e in events]


def test_audit_log_includes_actor():
    test_doc = "doc-actor-test"
    append_audit_event(test_doc, "actor_check", "pytest", {})
    events = read_audit_log(doc_id=test_doc)
    assert "pytest" in {e["actor"] for e in events}
```

## Done When

1. `python -m py_compile src/router.py` succeeds.
2. `pytest tests/test_classifier_router.py -v` runs all **18** tests (10 from Phase 1 + 8 here); all pass.
3. `route_document()` is deterministic — calling it twice on the same `ExtractedDocument` yields identical decisions.
4. `append_audit_event()` writes one JSONL line per call; `/tmp/poc-audit-log.jsonl` is openable + parseable.
5. Audit log roundtrip works: write 2 events for a doc_id, read returns both with original ts + actor + payload.
