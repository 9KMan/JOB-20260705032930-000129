---
phase: 1
decision: "Can we classify real tax forms with PoC-grade logic?"
plan: classifier-baseline
type: standard
wave: 1
depends_on: []
files_modified: [src/document_classifier.py, samples/, tests/test_classifier_router.py]
autonomous: true
acceptance_decision: "PASS if all 10 classifier/extract tests pass against 5 synthetic samples + classify_k1 reaches confidence >= 0.7 against the K-1 sample (currently the hardest form)."
---

# Phase 01 — Classifier Baseline

## Question this phase answers

> "Can a pure-Python regex+heuristic classifier correctly identify the 5 highest-volume tax form types (W-2, 1099-DIV, 1099-INT, 1099-B, K-1 page 1) at a confidence level worth trusting?"

## Decision outcome

| Approach | Pass | Fail |
|---|---|---|
| Regex keyword match + heuristic confidence scoring | ≥ 90% accuracy on 5 form types with 0.7+ confidence | Mixed accuracy / unpredictable confidence |

If **pass**: Phase 2 can trust the classification signal to gate routing decisions.
If **fail**: Phase 2 must either tolerate misclassification (defensive routing) or block until Phase 1 is rebuilt with an LLM.

## Files to Create

src/document_classifier.py
samples/w2-sample-001.txt
samples/1099-div-sample-001.txt
samples/1099-int-sample-001.txt
samples/1099-b-sample-001.txt
samples/k1-sample-001.txt
samples/unknown-sample-001.txt
tests/test_classifier_router.py

## Tasks

### Task 01 — DocType enum + 12-rule classifier

Build `src/document_classifier.py` with:

1. `class DocType(str, Enum)` enumerating: W2, FORM_1099_DIV, FORM_1099_INT, FORM_1099_MISC, FORM_1099_NEC, FORM_1099_B, K1_PAGE1, ENGAGEMENT_LETTER, ORGANIZER, UNKNOWN (10 values).
2. `_CLASSIFY_RULES: list[tuple[re.Pattern, DocType]]` with **12 ordered regex patterns** (most specific first).
3. `classify(text) -> tuple[DocType, float]` — confidence is `min(0.7 + 0.08 * (count - 1), 0.95)`; returns highest-confidence match.

### Task 02 — Per-form field extractors (5 extractors)

`_extract_w2`, `_extract_1099_div`, `_extract_1099_int`, `_extract_1099_b`, `_extract_k1` — each returning a `dict[str, ExtractedField]`. Fields use `_extract_after_label()` (tolerant of line-wrap and partial matches).

### Task 03 — Idempotent extract_document()

`extract_document(text, *, doc_type=None, document_id=None) -> ExtractedDocument` keyed by SHA-256 of text → `doc-<16hex>`. Dispatch by doc_type to the right per-form extractor.

### Task 04 — Six synthetic sample documents

Tax-form-shaped text with placeholder EINs/TINs (no real PII). Five training-set forms + one "unknown" control sample.

### Task 05 — Ten pytest tests

Each test is one assertion: classify/extract produces the expected outcome on a known sample.

## Code blocks

```file:src/document_classifier.py
"""PoC: CPA Document Classifier + Extractor

Honest PoC scope; production swaps in Tesseract + Claude/GPT-4o per OUT_OF_SCOPE.md.

Each public function returns the simplest correct answer — no OCR, no LLM calls.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class DocType(str, Enum):
    W2 = "W-2"
    FORM_1099_DIV = "1099-DIV"
    FORM_1099_INT = "1099-INT"
    FORM_1099_MISC = "1099-MISC"
    FORM_1099_NEC = "1099-NEC"
    FORM_1099_B = "1099-B"
    K1_PAGE1 = "K-1 (page 1)"
    ENGAGEMENT_LETTER = "Engagement Letter"
    ORGANIZER = "Organizer"
    UNKNOWN = "Unknown"


_CLASSIFY_RULES: list[tuple[re.Pattern, DocType]] = [
    (re.compile(r"\bform\s+w[\s-]?2\b", re.I), DocType.W2),
    (re.compile(r"\bwage\s+and\s+tax\s+statement\b", re.I), DocType.W2),
    (re.compile(r"\b1099[\s-]?div\b", re.I), DocType.FORM_1099_DIV),
    (re.compile(r"\bdividend.*distribution", re.I), DocType.FORM_1099_DIV),
    (re.compile(r"\b1099[\s-]?int\b", re.I), DocType.FORM_1099_INT),
    (re.compile(r"\binterest\s+income\b", re.I), DocType.FORM_1099_INT),
    (re.compile(r"\b1099[\s-]?misc\b", re.I), DocType.FORM_1099_MISC),
    (re.compile(r"\b1099[\s-]?nec\b", re.I), DocType.FORM_1099_NEC),
    (re.compile(r"\b1099[\s-]?b\b", re.I), DocType.FORM_1099_B),
    (re.compile(r"\bschedule\s+k[\s-]?1\b", re.I), DocType.K1_PAGE1),
    (re.compile(r"\bpartner['\u2019]s\s+share", re.I), DocType.K1_PAGE1),
    (re.compile(r"\bengagement\s+letter\b", re.I), DocType.ENGAGEMENT_LETTER),
    (re.compile(r"\borganizer\b", re.I), DocType.ORGANIZER),
]


def classify(text: str) -> tuple[DocType, float]:
    """Return (DocType, confidence). Highest-confidence rule wins."""
    if not text or not text.strip():
        return DocType.UNKNOWN, 0.0
    best: tuple[DocType, float] = (DocType.UNKNOWN, 0.0)
    for pattern, doc_type in _CLASSIFY_RULES:
        count = len(pattern.findall(text))
        if count == 0:
            continue
        conf = min(0.7 + 0.08 * (count - 1), 0.95)
        if conf > best[1]:
            best = (doc_type, conf)
    return best


def _parse_money(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace("$", "").replace(",", "")
    try:
        return round(float(s), 2)
    except (ValueError, TypeError):
        return None


def _extract_after_label(text: str, label_pattern: str,
                        value_pattern: str = r"\$?[\s\d,]*\d+\.?\d{0,2}") -> str | None:
    """Tolerant extractor: find label, scan next 400 chars for value."""
    label_re = re.compile(label_pattern, re.I)
    value_re = re.compile(value_pattern)
    m = label_re.search(text)
    if not m:
        return None
    tail = text[m.end(): m.end() + 400]
    v = value_re.search(tail)
    if v:
        return v.group(0).strip()
    fallback = re.search(r"(\$?\s*[\d,]+(?:\.\d{1,2})?)", tail)
    return fallback.group(1).strip() if fallback else None


@dataclass
class ExtractedField:
    value: Any
    confidence: float
    source: str
    notes: str | None = None


@dataclass
class ExtractedDocument:
    doc_type: DocType
    document_id: str
    classification_confidence: float
    fields: dict[str, ExtractedField]
    raw_text_hash: str
    extracted_at: str
    extracted_by: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["doc_type"] = self.doc_type.value
        return d


def _extract_w2(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    for box_name, label_pattern, conf in [
        ("box1_wages", r"box\s*1[\.\:\)]?\s*wages", 0.85),
        ("box2_federal_withheld", r"box\s*2[\.\:\)]?\s*federal", 0.85),
        ("box3_ss_wages", r"box\s*3[\.\:\)]?\s*social", 0.80),
        ("box4_ss_withheld", r"box\s*4[\.\:\)]?\s*social", 0.80),
    ]:
        v = _extract_after_label(text, label_pattern)
        m = _parse_money(v) if v else None
        fields[box_name] = ExtractedField(value=m, confidence=conf if m is not None else 0.0, source="regex")
    ein_re = re.compile(r"\b(\d{2}-\d{7})\b")
    m = ein_re.search(text)
    fields["employer_ein"] = ExtractedField(value=m.group(1) if m else None, confidence=0.9 if m else 0.0, source="regex")
    return fields


def _extract_1099_div(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    for box_name, label_pattern, conf in [
        ("box1a_ordinary_dividends", r"box\s*1a[\.\:\)]?\s*total\s+ordinary\s+dividends", 0.85),
        ("box1b_qualified_dividends", r"box\s*1b[\.\:\)]?\s*qualified\s+dividends", 0.80),
    ]:
        v = _extract_after_label(text, label_pattern)
        m = _parse_money(v) if v else None
        fields[box_name] = ExtractedField(value=m, confidence=conf if m is not None else 0.0, source="regex")
    tin_re = re.compile(r"\b(\d{2}-\d{7})\b")
    m = tin_re.search(text)
    fields["payer_tin"] = ExtractedField(value=m.group(1) if m else None, confidence=0.9 if m else 0.0, source="regex")
    return fields


def _extract_1099_int(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    v = _extract_after_label(text, r"box\s*1[\.\:\)]?\s*interest\s+income")
    m = _parse_money(v) if v else None
    fields["box1_interest"] = ExtractedField(value=m, confidence=0.85 if m is not None else 0.0, source="regex")
    return fields


def _extract_1099_b(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    desc = _extract_after_label(text, r"box\s*1a[\.\:\)]?")
    fields["box1a_description"] = ExtractedField(
        value=desc.strip() if desc else None,
        confidence=0.7 if desc else 0.0, source="regex")
    v = _extract_after_label(text, r"box\s*2[\.\:\)]?\s*proceeds")
    m = _parse_money(v) if v else None
    fields["box2_proceeds"] = ExtractedField(value=m, confidence=0.85 if m is not None else 0.0, source="regex")
    return fields


def _extract_k1(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    for box_name, label_pattern, conf in [
        ("part3_line1_ordinary_income", r"line\s*1[\.\:\)]?\s*ordinary\s+business", 0.80),
        ("part3_line5_interest", r"line\s*5[\.\:\)]?\s*interest\s+income", 0.80),
    ]:
        v = _extract_after_label(text, label_pattern)
        m = _parse_money(v) if v else None
        fields[box_name] = ExtractedField(value=m, confidence=conf if m is not None else 0.0, source="regex")
    pct_re = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
    m = pct_re.search(text)
    fields["partner_share_pct"] = ExtractedField(value=float(m.group(1)) if m else None, confidence=0.7 if m else 0.0, source="regex")
    return fields


_DISPATCH: dict[DocType, callable] = {
    DocType.W2: _extract_w2,
    DocType.FORM_1099_DIV: _extract_1099_div,
    DocType.FORM_1099_INT: _extract_1099_int,
    DocType.FORM_1099_B: _extract_1099_b,
    DocType.K1_PAGE1: _extract_k1,
}


def extract_document(text: str, *, doc_type: DocType | None = None,
                    document_id: str | None = None) -> ExtractedDocument:
    """Idempotent: same text -> same document_id."""
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    doc_id = document_id or f"doc-{text_hash}"
    if doc_type is None:
        doc_type, cls_conf = classify(text)
    else:
        cls_conf = 1.0
    extractor = _DISPATCH.get(doc_type)
    fields = extractor(text) if extractor else {}
    return ExtractedDocument(
        doc_type=doc_type,
        document_id=doc_id,
        classification_confidence=cls_conf,
        fields=fields,
        raw_text_hash=text_hash,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        extracted_by="poc-regex-v0",
    )
```

```file:samples/w2-sample-001.txt
Form W-2 — Wage and Tax Statement (SAMPLE / SYNTHETIC — NO REAL PII)
Employee:  ACME TEST CORP
Employer EIN:    12-3456789
Tax Year:  2025
Box 1 Wages, tips, other compensation:   $75,000.00
Box 2 Federal income tax withheld:      $11,250.00
Box 3 Social security wages:             $75,000.00
Box 4 Social security tax withheld:     $4,650.00
```

```file:samples/1099-div-sample-001.txt
Form 1099-DIV (SAMPLE)
Payer:  TEST BROKERAGE LLC
Payer TIN:  98-7654321
Box 1a Total ordinary dividends:           $4,250.00
Box 1b Qualified dividends:                $3,200.00
Box 4  Federal income tax withheld:           $637.50
```

```file:samples/1099-int-sample-001.txt
Form 1099-INT (SAMPLE)
Payer:  SAMPLE BANK, N.A.
Payer TIN:  11-2233445
Box 1 Interest income:           $1,250.00
```

```file:samples/1099-b-sample-001.txt
Form 1099-B (SAMPLE)
Payer:  SAMPLE BROKERAGE INC
Payer TIN:  22-3344556
Box 1a Description:  100 sh VTI (ETF)
Box 2  Proceeds:           $24,500.00
Box 3  Cost or other basis: $20,000.00
```

```file:samples/k1-sample-001.txt
Schedule K-1 (Form 1065) (SAMPLE)
Partnership: TEST LIMITED PARTNERSHIP
Partnership EIN:  55-9988776
Line 1 Ordinary business income (loss):   $125,000.00
Line 5 Interest income:                  $5,200.00
Partner's share of profit: 50%
```

```file:samples/unknown-sample-001.txt
[generic plaintext — no tax form markers]
Total: $0.00
Date: 2025-03-15
```

```file:tests/test_classifier_router.py
"""Tests for Phase 01 (classifier) and Phase 02 (router+audit) together.

Run: pytest tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from document_classifier import DocType, classify, extract_document

REPO = Path(__file__).parent.parent

# Phase 01 tests ----------------------------------------------------------------

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
```

## Done When

1. `python -m py_compile src/document_classifier.py` succeeds.
2. `pytest tests/test_classifier_router.py -v -k "classify or extract"` runs all 10 tests, **all pass**.
3. The K-1 classifier reaches ≥ 0.7 confidence (the hardest form — K-1's `Schedule K-1` text is the only form that mentions "partner's share").
4. All 6 sample files exist on disk with placeholder PII only (EINs like `12-3456789`, TINs like `98-7654321`).
5. **Same text → same `document_id`** (idempotency check passes).
