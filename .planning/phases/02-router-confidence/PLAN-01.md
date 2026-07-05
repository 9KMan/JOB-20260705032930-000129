---
phase: 2
decision: "Does the rule router respect confidences without false-trusting low-confidence routing?"
plan: router-and-confidence
type: standard
wave: 1
depends_on: [1]
files_modified: [src/router.py]
autonomous: true
acceptance_decision: "PASS if all 6 routing tests pass: W-2/1099-DIV route to PREPARER; K-1 routes to SENIOR; unknown routes to SENIOR; artificially-low-confidence field demotes to SENIOR; same ExtractedDocument yields identical decision; custom rule table overrides defaults."
---

# Phase 02 — Router + Confidence Demotion

## Question this phase answers

> "Given an ExtractedDocument, does the rule-based router make the right routing decision — including the case where classification confidence or per-field confidence is too low to trust a preparer-routed doc?"

## Decision outcome

| Approach | Pass | Fail |
|---|---|---|
| Hardcoded DEFAULT_RULES + confidence demotion at 0.5/0.65/0.7 thresholds | All 6 routing tests pass; K-1 goes to senior by design; W-2 low-confidence force-promotes | Mixed routing / non-deterministic behavior |

If **pass**: Phase 3 can wire audit append behind this routing decision.
If **fail**: Phase 3 either rejects low-confidence docs at the gate, or Phase 1 must rebuild classifier.

## Files to Create

src/router.py

## Tasks

### Task 01 — Route enum + RoutingRule dataclass + DEFAULT_RULES

```file:src/router.py
"""Rule + confidence router. Idempotent: same input -> same decision."""
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
    """Maps doc_type (with optional condition) -> Route."""
    doc_type: DocType
    condition: str | None
    route: Route
    reason: str


DEFAULT_RULES: list[RoutingRule] = [
    RoutingRule(DocType.W2, None, Route.PREPARER_QUEUE, "W-2 high-volume low-risk -> preparer"),
    RoutingRule(DocType.FORM_1099_DIV, None, Route.PREPARER_QUEUE, "1099-DIV -> preparer"),
    RoutingRule(DocType.FORM_1099_INT, None, Route.PREPARER_QUEUE, "1099-INT -> preparer"),
    RoutingRule(DocType.FORM_1099_B, None, Route.PREPARER_QUEUE, "1099-B -> preparer"),
    RoutingRule(DocType.K1_PAGE1, None, Route.SENIOR_REVIEWER, "K-1 partnership-level -> senior"),
    RoutingRule(DocType.ENGAGEMENT_LETTER, None, Route.SENIOR_REVIEWER, "Engagement letter -> senior"),
    RoutingRule(DocType.ORGANIZER, None, Route.SENIOR_REVIEWER, "Organizer -> senior"),
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
    """Pure routing function. Three demotion gates in priority order:
    1. classification_confidence < 0.5 -> senior (could be misclassified)
    2. classification_confidence in (0.5, 0.65) AND current route is preparer -> senior
    3. any field confidence < 0.7 AND current route is preparer -> senior
    """
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
        reason = f"Classification confidence {doc.classification_confidence:.2f} < 0.5"
    elif doc.classification_confidence < 0.65 and route == Route.PREPARER_QUEUE:
        route = Route.SENIOR_REVIEWER
        reason = f"Classification confidence {doc.classification_confidence:.2f} in (0.5, 0.65)"

    flagged = _flagged_fields(doc.fields, threshold=0.7)
    if flagged and route == Route.PREPARER_QUEUE:
        route = Route.SENIOR_REVIEWER
        reason = f"Field extraction flagged: {', '.join(flagged)}"

    return RoutingDecision(
        document_id=doc.document_id,
        route=route,
        rule_matched=reason,
        classification_confidence=doc.classification_confidence,
        avg_field_confidence=_avg_confidence(doc.fields),
        flagged_fields=flagged,
    )
```

### Task 02 — Append `tests/test_classifier_router.py` with 6 routing tests

```python
# (add to tests/test_classifier_router.py after the Phase 01 tests)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from router import Route, RoutingRule, route_document


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
    e1 = extract_document(text)
    e2 = extract_document(text)
    d1 = route_document(e1)
    d2 = route_document(e2)
    assert d1.route == d2.route
    assert d1.document_id == d2.document_id


def test_route_with_custom_rule_table():
    custom = [RoutingRule(DocType.W2, None, Route.SENIOR_REVIEWER, "demote W-2 for test")]
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    decision = route_document(extracted, rules=custom)
    assert decision.route == Route.SENIOR_REVIEWER
```

## Done When

1. `python -m py_compile src/router.py` succeeds.
2. `pytest tests/test_classifier_router.py -v -k "route"` runs 6 routing tests; all pass.
3. `route_document()` is **idempotent** — same `ExtractedDocument` twice yields the same `RoutingDecision`.
4. The `< 0.5` confidence gate fires for `unknown-sample-001.txt` (confidence = 0.0).
5. Custom rule table overrides DEFAULT_RULES.
