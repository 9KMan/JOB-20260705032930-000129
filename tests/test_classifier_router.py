"""Test the PoC's classification + routing + idempotency.

Run: pytest tests/

Covers:
- Classify() against W-2, 1099-DIV, 1099-INT, K-1, generic text
- extract_document() returns all expected fields per type
- route_document() preference: preparer > senior > DLQ
- route_document() demotion to senior on low confidence / flagged fields
- Idempotency: same text → same doc_id
- Audit log: append + read roundtrip
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from document_classifier import (
    DocType,
    classify,
    extract_document,
)
from router import (
    DEFAULT_RULES,
    Route,
    RoutingRule,
    append_audit_event,
    read_audit_log,
    route_document,
)

REPO = Path(__file__).parent.parent


# ── Classification ──────────────────────────────────────────────────────────


def test_classify_w2():
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    doc_type, confidence = classify(text)
    assert doc_type == DocType.W2
    assert confidence >= 0.7


def test_classify_1099_div():
    text = (REPO / "samples" / "1099-div-sample-001.txt").read_text()
    doc_type, confidence = classify(text)
    assert doc_type == DocType.FORM_1099_DIV
    assert confidence >= 0.7


def test_classify_1099_int():
    text = (REPO / "samples" / "1099-int-sample-001.txt").read_text()
    doc_type, confidence = classify(text)
    assert doc_type == DocType.FORM_1099_INT
    assert confidence >= 0.7


def test_classify_k1():
    text = (REPO / "samples" / "k1-sample-001.txt").read_text()
    doc_type, confidence = classify(text)
    assert doc_type == DocType.K1_PAGE1
    assert confidence >= 0.7


def test_classify_unknown():
    text = (REPO / "samples" / "unknown-sample-001.txt").read_text()
    doc_type, _ = classify(text)
    assert doc_type == DocType.UNKNOWN


def test_classify_empty():
    doc_type, conf = classify("")
    assert doc_type == DocType.UNKNOWN
    assert conf == 0.0


# ── Extraction ──────────────────────────────────────────────────────────────


def test_extract_w2_finds_box1_and_ein():
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    assert extracted.doc_type == DocType.W2
    assert "box1_wages" in extracted.fields
    assert extracted.fields["box1_wages"].value == pytest.approx(75000.00, rel=1e-3)
    assert "employer_ein" in extracted.fields
    assert extracted.fields["employer_ein"].value == "12-3456789"


def test_extract_1099_div_finds_box1a_and_payer_tin():
    text = (REPO / "samples" / "1099-div-sample-001.txt").read_text()
    extracted = extract_document(text)
    assert extracted.doc_type == DocType.FORM_1099_DIV
    assert extracted.fields["box1a_ordinary_dividends"].value == pytest.approx(4250.00, rel=1e-3)
    assert extracted.fields["payer_tin"].value == "98-7654321"


def test_extract_k1_finds_partner_share_and_line1():
    text = (REPO / "samples" / "k1-sample-001.txt").read_text()
    extracted = extract_document(text)
    assert extracted.doc_type == DocType.K1_PAGE1
    assert extracted.fields["partner_share_pct"].value == pytest.approx(50.0, rel=1e-3)
    assert extracted.fields["part3_line1_ordinary_income"].value == pytest.approx(125000.00, rel=1e-3)


def test_extract_is_idempotent_same_text_same_doc_id():
    text = "Form W-2 ... Box 1 wages $50,000.00"
    e1 = extract_document(text)
    e2 = extract_document(text)
    assert e1.document_id == e2.document_id
    assert e1.raw_text_hash == e2.raw_text_hash


# ── Routing ────────────────────────────────────────────────────────────────


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
    """If a field has very low confidence, even a normally preparer-routed
    doc should land in the senior queue."""
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    # Manually corrupt a field's confidence to trigger demotion
    extracted.fields["box1_wages"].confidence = 0.3
    decision = route_document(extracted)
    assert decision.route == Route.SENIOR_REVIEWER
    assert "box1_wages" in decision.flagged_fields


def test_route_is_idempotent():
    """Running the same doc through twice produces the same routing decision."""
    text = (REPO / "samples" / "1099-div-sample-001.txt").read_text()
    e1 = extract_document(text)
    e2 = extract_document(text)
    d1 = route_document(e1)
    d2 = route_document(e2)
    assert d1.route == d2.route
    assert d1.document_id == d2.document_id


def test_route_with_custom_rule_table():
    """Demonstrates rule injection (real impl loads from YAML)."""
    custom_rules: list[RoutingRule] = [
        RoutingRule(DocType.W2, None, Route.SENIOR_REVIEWER, "demote W-2 to senior for testing"),
    ]
    text = (REPO / "samples" / "w2-sample-001.txt").read_text()
    extracted = extract_document(text)
    decision = route_document(extracted, rules=custom_rules)
    assert decision.route == Route.SENIOR_REVIEWER


# ── Audit log ─────────────────────────────────────────────────────────────


def test_audit_log_append_and_read():
    """Roundtrip: append two events for doc-X, then read them back."""
    test_doc = "doc-test123"
    append_audit_event(test_doc, "test_event_1", "pytest", {"hello": "world"})
    append_audit_event(test_doc, "test_event_2", "pytest", {"hello": "again"})

    events = read_audit_log(doc_id=test_doc)
    assert len(events) >= 2
    event_types = [e["event_type"] for e in events]
    assert "test_event_1" in event_types
    assert "test_event_2" in event_types


def test_audit_log_includes_actor():
    """Every audit event should carry an actor for accountability."""
    test_doc = "doc-actor-test"
    append_audit_event(test_doc, "actor_check", "pytest", {})
    events = read_audit_log(doc_id=test_doc)
    actors = {e["actor"] for e in events}
    assert "pytest" in actors
