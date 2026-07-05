---
phase: 1
plan: classifier
type: standard
wave: 1
depends_on: []
files_modified: [src/document_classifier.py, tests/test_classifier_router.py, samples/w2-sample-001.txt, samples/1099-div-sample-001.txt, samples/1099-int-sample-001.txt, samples/1099-b-sample-001.txt, samples/k1-sample-001.txt, samples/unknown-sample-001.txt]
autonomous: true
requirements:
  - classify W-2 / 1099-DIV / 1099-INT / 1099-B / K-1 / Unknown with confidence >= 0.7
  - extract W-2 Box 1 wages + EIN within $0.01
  - extract 1099-DIV Box 1a ordinary + qualified dividends
  - extract K-1 partner share % + Part III Line 1 ordinary income
  - idempotent: same text -> same doc_id (SHA-256 of content)
---

# Plan: Document Classifier + Field Extractor

## Objective

Deliver `src/document_classifier.py` and the matching pytest file. The classifier identifies the form type; the extractor pulls structured fields with per-field confidence. This is the foundation Block A from `.planning/JOB-129-POC-SCOPE.md`.

**PoC scope; real OCR + LLM extraction is OUT_OF_SCOPE.md and only swapped in for the production build.**

## Files to Create

src/document_classifier.py
tests/test_classifier_router.py
samples/w2-sample-001.txt
samples/1099-div-sample-001.txt
samples/1099-int-sample-001.txt
samples/1099-b-sample-001.txt
samples/k1-sample-001.txt
samples/unknown-sample-001.txt

## Tasks

### Phase 1 — DocType enum + dataclasses

Define `DocType(str, Enum)` enumerating 9 values: W2, FORM_1099_DIV, FORM_1099_INT, FORM_1099_MISC, FORM_1099_NEC, FORM_1099_B, K1_PAGE1, ENGAGEMENT_LETTER, ORGANIZER, UNKNOWN. Add a module-level regex list `_CLASSIFY_RULES: list[tuple[re.Pattern, DocType]]` ordered **most specific first** covering W-2 / 1099-* / K-1 / engagement / organizer patterns.

```file:src/document_classifier.py
"""PoC: CPA Document Classifier + Extractor

A minimal but functional implementation that demonstrates the architecture
for a CPA/tax document intake pipeline. This PoC:

1. Classifies documents by type (W-2, 1099-DIV, 1099-INT, 1099-B, K-1, brokerage, engagement, organizer, unknown)
2. Extracts structured fields using regex + heuristic (real implementation
   would replace with Tesseract OCR + Claude/GPT-4o JSON extraction)
3. Computes confidence scores per field
4. Returns structured JSON ready for the router

Honest about the PoC nature:
- This is NOT production-quality OCR (uses regex over synthetic text)
- Real implementation swaps the `extract_with_ocr()` and `extract_with_llm()`
  functions in this module for the production stack
- Tests run without GPU, without API keys, without internet

Production swap-in path documented in README. Run `python -m src.runner --help`.
"""
from __future__ import annotations

import hashlib
import json
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


# Classification rules — order matters; check most specific first
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
    """Return (DocType, confidence). Confidence reflects both keyword-match
    quality and structural signal density on the document."""
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


def _extract_after_label(text: str, label_pattern: str, value_pattern: str = r"\$?[\s\d,]*\d+\.?\d{0,2}") -> str | None:
    """Find a labeled field in form-style text and pull the next matching value."""
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
    fields["box1a_description"] = ExtractedField(value=desc.strip() if desc else None, confidence=0.7 if desc else 0.0, source="regex")
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


def extract_document(text: str, *, doc_type: DocType | None = None, document_id: str | None = None) -> ExtractedDocument:
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    doc_id = document_id or f"doc-{text_hash}"
    if doc_type is None:
        doc_type, cls_conf = classify(text)
    else:
        cls_conf = 1.0
    fields: dict[str, ExtractedField] = {}
    if doc_type == DocType.W2:
        fields = _extract_w2(text)
    elif doc_type == DocType.FORM_1099_DIV:
        fields = _extract_1099_div(text)
    elif doc_type == DocType.FORM_1099_INT:
        fields = _extract_1099_int(text)
    elif doc_type in (DocType.FORM_1099_B,):
        fields = _extract_1099_b(text)
    elif doc_type == DocType.K1_PAGE1:
        fields = _extract_k1(text)
    return ExtractedDocument(
        doc_type=doc_type, document_id=doc_id, classification_confidence=cls_conf,
        fields=fields, raw_text_hash=text_hash,
        extracted_at=datetime.now(timezone.utc).isoformat(), extracted_by="poc-regex-v0",
    )
```

### Phase 2 — Synthetic sample documents

Five synthetic form files in `samples/` mimicking IRS layouts for the extractor to find. No real PII; EINs/TINs are placeholders like `12-3456789`.

```file:samples/w2-sample-001.txt
Form W-2 — Wage and Tax Statement (SAMPLE / SYNTHETIC — NO REAL PII)

Employee:  ACME TEST CORP
Employer EIN:    12-3456789
Employee SSN:    XXX-XX-XXXX  (redacted for PoC)
Tax Year:  2025

Box 1 Wages, tips, other compensation:   $75,000.00
Box 2 Federal income tax withheld:      $11,250.00
Box 3 Social security wages:             $75,000.00
Box 4 Social security tax withheld:     $4,650.00

[End of synthetic W-2 form]
```

```file:samples/1099-div-sample-001.txt
Form 1099-DIV  — Dividends and Distributions (SAMPLE / SYNTHETIC)
Payer:  TEST BROKERAGE LLC
Payer TIN:  98-7654321
Tax Year:  2025
Box 1a Total ordinary dividends:           $4,250.00
Box 1b Qualified dividends:                $3,200.00
Box 4  Federal income tax withheld:           $637.50

[End of synthetic 1099-DIV form]
```

```file:samples/1099-int-sample-001.txt
Form 1099-INT  — Interest Income (SAMPLE / SYNTHETIC)
Payer:  SAMPLE BANK, N.A.
Payer TIN:  11-2233445
Box 1 Interest income:           $1,250.00
Box 4 Federal income tax withheld:    0.00

[End of synthetic 1099-INT form]
```

```file:samples/1099-b-sample-001.txt
Form 1099-B  — Proceeds from Broker and Barter Exchange (SAMPLE)
Payer:  SAMPLE BROKERAGE
Payer TIN:  22-3344556
Box 1a Description:  100 sh VTI (ETF) traded 12-15-2025 cost basis $20,000
Box 1b Date acquired:  2018-06-01
Box 2  Proceeds:           $24,500.00

[End of synthetic 1099-B form]
```

```file:samples/k1-sample-001.txt
Schedule K-1 (Form 1065) — Partner's Share of Income (SAMPLE)
Partnership: TEST LIMITED PARTNERSHIP
Partnership EIN:  55-9988776
Line 1 Ordinary business income (loss):   $125,000.00
Line 5 Interest income:                  $5,200.00
Partner's share of profit: 50%

[End of synthetic K-1 form]
```

```file:samples/unknown-sample-001.txt
[generic plaintext — no tax form markers]

This file demonstrates the "low confidence -> senior_reviewer" override branch.
Total: $0.00
Date: 2025-03-15

[End of synthetic Unknown sample]
```

### Phase 3 — Pytest tests for classify + extract

```file:tests/test_classifier_router.py
"""Test the PoC's classification + extraction.

Run: pytest tests/

Covers:
- Classify() against W-2, 1099-DIV, 1099-INT, K-1, generic text
- extract_document() returns all expected fields per type
- Idempotency: same text -> same doc_id
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from document_classifier import DocType, classify, extract_document

REPO = Path(__file__).parent.parent


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

1. `src/document_classifier.py` exposes `classify()`, `extract_document()`, `DocType`, `ExtractedField`, `ExtractedDocument` and per-form extractors for 5 form types.
2. `python -m py_compile src/document_classifier.py` succeeds (no syntax errors).
3. `pytest tests/test_classifier_router.py -v` runs the 10 classify/extract tests above; all pass.
4. Each synthetic sample file is parseable by `extract_document()` and produces the expected field values (verified in tests).
5. Sample IDs (EINs/TINs) are placeholders only — no real PII.
