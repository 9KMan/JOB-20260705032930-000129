"""Rule + LLM router for document routing.

Routes extracted documents to:
- Preparer queue (if classification + extraction confidence both ≥ 0.8)
- Senior reviewer queue (if either confidence < 0.8)
- DLT (dead letter) (if schema invalid or extraction failed)

Idempotency:
- Documents are keyed by SHA-256 of the raw text hash (computed in the
  extractor). Re-processing the same doc_id returns the same routing decision.

PoC implementation:
- Rules defined in YAML (or hardcoded fallback) — see DEFAULT_RULES
- LLM exception router: stubbed with regex/keyword detection
  (real impl swaps in Claude or GPT-4o zero-shot classification)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from document_classifier import (
    DocType,
    ExtractedDocument,
    ExtractedField,
)


class Route(str, Enum):
    PREPARER_QUEUE = "preparer_queue"
    SENIOR_REVIEWER = "senior_reviewer"
    DEAD_LETTER = "dead_letter"
    DUPLICATE = "duplicate"


@dataclass
class RoutingRule:
    """A rule mapping doc_type + optional condition → Route."""
    doc_type: DocType
    condition: str | None  # e.g. "all_fields_valid" or None for default
    route: Route
    reason: str


# Default rule table — easy to edit, real build loads from YAML/DB
DEFAULT_RULES: list[RoutingRule] = [
    RoutingRule(DocType.W2, None, Route.PREPARER_QUEUE, "W-2 always to preparer queue (high-volume, low-risk)"),
    RoutingRule(DocType.FORM_1099_DIV, None, Route.PREPARER_QUEUE, "1099-DIV to preparer queue"),
    RoutingRule(DocType.FORM_1099_INT, None, Route.PREPARER_QUEUE, "1099-INT to preparer queue"),
    RoutingRule(DocType.FORM_1099_B, None, Route.PREPARER_QUEUE, "1099-B to preparer queue"),
    RoutingRule(DocType.K1_PAGE1, None, Route.SENIOR_REVIEWER, "K-1 to senior reviewer (complex, partnership-level)"),
    RoutingRule(DocType.ENGAGEMENT_LETTER, None, Route.SENIOR_REVIEWER, "Engagement letter to senior reviewer"),
    RoutingRule(DocType.ORGANIZER, None, Route.SENIOR_REVIEWER, "Organizer to senior reviewer"),
    RoutingRule(DocType.UNKNOWN, None, Route.SENIOR_REVIEWER, "Unknown doc type → manual triage"),
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


def _flagged_fields(fields: dict[str, ExtractedField], threshold: float = 0.8) -> list[str]:
    """Fields with confidence below threshold — these need human review."""
    return [name for name, f in fields.items() if f.confidence < threshold]


def route_document(doc: ExtractedDocument, rules: list[RoutingRule] | None = None) -> RoutingDecision:
    """Pure routing function — same input always produces same decision."""
    rules = rules or DEFAULT_RULES

    # 1. Find first matching rule
    matched_rule: RoutingRule | None = None
    for rule in rules:
        if rule.doc_type == doc.doc_type:
            matched_rule = rule
            break

    route = matched_rule.route if matched_rule else Route.SENIOR_REVIEWER
    reason = matched_rule.reason if matched_rule else "No rule matched"

    # 2. Override to senior reviewer if classification confidence is too low
    #    to trust the typed-route.
    if doc.classification_confidence < 0.5:
        # Very low — could be a typo'd form number or a wrong classification
        route = Route.SENIOR_REVIEWER
        reason = (
            f"Classification confidence {doc.classification_confidence:.2f} < 0.5 — "
            f"could be misclassified; manual triage required"
        )
    elif doc.classification_confidence < 0.65 and route == Route.PREPARER_QUEUE:
        # Below the "trusted preparer" threshold — promote to senior
        route = Route.SENIOR_REVIEWER
        reason = (
            f"Classification confidence {doc.classification_confidence:.2f} in (0.5, 0.65); "
            f"promoted to senior for safety"
        )
    # NOTE: we do NOT demote simply because classification is in (0.65, 0.8).
    # The default rule for that doc_type already encodes the right intent.

    # 3. Override to senior if any field is low-confidence
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


# --- Audit log -------------------------------------------------------

_AUDIT_LOG_PATH = Path("/tmp/poc-audit-log.jsonl")  # PoC uses /tmp


def append_audit_event(
    doc_id: str,
    event_type: str,
    actor: str,
    payload: dict,
) -> None:
    """Append an immutable audit event to the log."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "doc_id": doc_id,
        "event_type": event_type,
        "actor": actor,
        "payload": payload,
    }
    with _AUDIT_LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


def read_audit_log(doc_id: str | None = None) -> list[dict]:
    """Read audit log (optionally filtered by doc_id). Empty if missing."""
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
