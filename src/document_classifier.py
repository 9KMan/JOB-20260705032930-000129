"""PoC: CPA Document Classifier + Extractor

A minimal but functional implementation that demonstrates the architecture
for a CPA/tax document intake pipeline. This PoC:

1. Classifies documents by type (W-2, 1099-DIV, K-1, brokerage, organizer)
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

    # Score every rule and accumulate signal
    best: tuple[DocType, float] = (DocType.UNKNOWN, 0.0)
    for pattern, doc_type in _CLASSIFY_RULES:
        count = len(pattern.findall(text))
        if count == 0:
            continue
        # Base confidence: 0.7 per first match (firm detection)
        # Boost: +0.05 per extra mention up to 0.95 max
        conf = min(0.7 + 0.08 * (count - 1), 0.95)
        if conf > best[1]:
            best = (doc_type, conf)
    return best


# Field extractors per form type
_MONEY_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")


def _parse_money(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace("$", "").replace(",", "")
    try:
        return round(float(s), 2)
    except (ValueError, TypeError):
        return None


def _extract_after_label(text: str, label_pattern: str, value_pattern: str = r"\$?[\s\d,]*\d+\.?\d{0,2}") -> str | None:
    """Find a labeled field in form-style text and pull the next matching value.

    Tolerant: after matching the label, scan the next chunk of text for the
    first plausible money-like token. Works across line-wrapped PDFs.
    """
    label_re = re.compile(label_pattern, re.I)
    value_re = re.compile(value_pattern)
    m = label_re.search(text)
    if not m:
        return None
    # Bigger window to handle wrapped layouts
    tail = text[m.end(): m.end() + 400]
    v = value_re.search(tail)
    if v:
        return v.group(0).strip()
    # Fallback: first number anywhere after the label
    fallback = re.search(r"(\$?\s*[\d,]+(?:\.\d{1,2})?)", tail)
    return fallback.group(1).strip() if fallback else None


@dataclass
class ExtractedField:
    value: Any
    confidence: float  # 0.0..1.0
    source: str       # "regex", "ocr+llm", "manual"
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


def extract_document(
    text: str,
    *,
    doc_type: DocType | None = None,
    document_id: str | None = None,
) -> ExtractedDocument:
    """
    Classify (if not provided) and extract fields per doc_type.

    PoC: pure regex extraction with rule-based confidence.
    Real implementation: pass text through OCR → LLM JSON schema →
    cross-validate, then fall back here for low-confidence fields.
    """
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    doc_id = document_id or f"doc-{text_hash}"

    if doc_type is None:
        doc_type, cls_conf = classify(text)
    else:
        # Manual override — full confidence on type, but flag as "manual"
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
    # Other types have no PoC extractor (real build extends the schemas).

    return ExtractedDocument(
        doc_type=doc_type,
        document_id=doc_id,
        classification_confidence=cls_conf,
        fields=fields,
        raw_text_hash=text_hash,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        extracted_by="poc-regex-v0",
    )


def _extract_w2(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}

    # Box 1 — wages
    v = _extract_after_label(text, r"box\s*1[\.\:\)]?\s*wages")
    m = _parse_money(v) if v else None
    fields["box1_wages"] = ExtractedField(
        value=m, confidence=0.85 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 1 Wages' label",
    )

    # Box 2 — federal income tax withheld
    v = _extract_after_label(text, r"box\s*2[\.\:\)]?\s*federal")
    m = _parse_money(v) if v else None
    fields["box2_federal_withheld"] = ExtractedField(
        value=m, confidence=0.85 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 2 Federal Tax' label",
    )

    # Box 3 — social security wages
    v = _extract_after_label(text, r"box\s*3[\.\:\)]?\s*social")
    m = _parse_money(v) if v else None
    fields["box3_ss_wages"] = ExtractedField(
        value=m, confidence=0.80 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 3 Social Security Wages'",
    )

    # Box 4 — social security tax withheld
    v = _extract_after_label(text, r"box\s*4[\.\:\)]?\s*social")
    m = _parse_money(v) if v else None
    fields["box4_ss_withheld"] = ExtractedField(
        value=m, confidence=0.80 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 4 Social Security Tax'",
    )

    # Employer EIN (Box b: Employer identification number)
    ein_re = re.compile(r"\b(\d{2}-\d{7})\b")
    m = ein_re.search(text)
    fields["employer_ein"] = ExtractedField(
        value=m.group(1) if m else None,
        confidence=0.9 if m else 0.0,
        source="regex",
        notes="matched NNN-NNNNNNN pattern",
    )

    return fields


def _extract_1099_div(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    # Box 1a — total ordinary dividends
    v = _extract_after_label(text, r"box\s*1a[\.\:\)]?\s*total\s+ordinary\s+dividends")
    m = _parse_money(v) if v else None
    fields["box1a_ordinary_dividends"] = ExtractedField(
        value=m, confidence=0.85 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 1a Total Ordinary Dividends'",
    )

    # Box 1b — qualified dividends
    v = _extract_after_label(text, r"box\s*1b[\.\:\)]?\s*qualified\s+dividends")
    m = _parse_money(v) if v else None
    fields["box1b_qualified_dividends"] = ExtractedField(
        value=m, confidence=0.80 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 1b Qualified Dividends'",
    )

    # Payer TIN
    tin_re = re.compile(r"\b(\d{2}-\d{7})\b")
    m = tin_re.search(text)
    fields["payer_tin"] = ExtractedField(
        value=m.group(1) if m else None,
        confidence=0.9 if m else 0.0,
        source="regex", notes="matched NNN-NNNNNNN pattern",
    )

    return fields


def _extract_1099_int(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    # Box 1 — interest income
    v = _extract_after_label(text, r"box\s*1[\.\:\)]?\s*interest\s+income")
    m = _parse_money(v) if v else None
    fields["box1_interest"] = ExtractedField(
        value=m, confidence=0.85 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 1 Interest Income'",
    )
    return fields


def _extract_1099_b(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    # Box 1a — description (regex gives free text)
    desc = _extract_after_label(text, r"box\s*1a[\.\:\)]?")
    fields["box1a_description"] = ExtractedField(
        value=desc.strip() if desc else None,
        confidence=0.7 if desc else 0.0,
        source="regex", notes="free text after Box 1a label",
    )

    # Box 2 — proceeds
    v = _extract_after_label(text, r"box\s*2[\.\:\)]?\s*proceeds")
    m = _parse_money(v) if v else None
    fields["box2_proceeds"] = ExtractedField(
        value=m, confidence=0.85 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Box 2 Proceeds'",
    )
    return fields


def _extract_k1(text: str) -> dict[str, ExtractedField]:
    fields: dict[str, ExtractedField] = {}
    # Part III line 1 — ordinary business income
    v = _extract_after_label(text, r"line\s*1[\.\:\)]?\s*ordinary\s+business")
    m = _parse_money(v) if v else None
    fields["part3_line1_ordinary_income"] = ExtractedField(
        value=m, confidence=0.80 if m is not None else 0.0,
        source="regex", notes="rule-extracted from 'Line 1 Ordinary Business Income'",
    )

    # Part III line 5 — interest income
    v = _extract_after_label(text, r"line\s*5[\.\:\)]?\s*interest\s+income")
    m = _parse_money(v) if v else None
    fields["part3_line5_interest"] = ExtractedField(
        value=m, confidence=0.80 if m is not None else 0.0,
        source="regex",
    )

    # Partner's share percentage
    pct_re = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
    m = pct_re.search(text)
    fields["partner_share_pct"] = ExtractedField(
        value=float(m.group(1)) if m else None,
        confidence=0.7 if m else 0.0,
        source="regex", notes="matched NNN.NN% pattern",
    )
    return fields
