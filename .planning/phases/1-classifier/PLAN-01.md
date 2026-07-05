---
phase: 1
plan: classifier
type: standard
wave: 1
depends_on: []
files_modified: [src/document_classifier.py, tests/test_classifier_router.py]
autonomous: true
requirements:
  - classify W-2 / 1099-DIV / 1099-INT / 1099-B / K-1 / Unknown with confidence >= 0.7
  - extract W-2 Box 1 wages + EIN within $0.01
  - extract 1099-DIV Box 1a ordinary + qualified dividends
  - extract K-1 partner share % + Part III Line 1 ordinary income
  - idempotent: same text -> same doc_id (SHA-256 of content)
---

# Phase 01: Document Classifier + Field Extractor

**Goal:** Deliver `src/document_classifier.py` and the matching pytest file. The classifier identifies the form type; the extractor pulls structured fields with per-field confidence. This is the foundation Block A from `.planning/JOB-129-POC-SCOPE.md`.

**Context:** PoC scope; real OCR + LLM extraction is OUT_OF_SCOPE.md and only swapped in for the production build.

## Tasks

### 1. DocType enum + dataclasses

**Wave:** 1
**Depends on:** —
**Files modified:** `src/document_classifier.py`

<action>
Create the file `src/document_classifier.py` with:

1. `from __future__ import annotations`
2. Standard-lib imports: `hashlib, json, re, dataclasses (asdict, dataclass, field), datetime (datetime, timezone), enum (Enum), pathlib (Path), typing (Any)`
3. `class DocType(str, Enum):` enumerating 9 values: W2, FORM_1099_DIV, FORM_1099_INT, FORM_1099_MISC, FORM_1099_NEC, FORM_1099_B, K1_PAGE1, ENGAGEMENT_LETTER, ORGANIZER, UNKNOWN
4. A module-level regex list `_CLASSIFY_RULES: list[tuple[re.Pattern, DocType]]` that orders **most specific first**:
   - W-2: `r"\bform\s+w[\s-]?2\b"` and `r"\bwage\s+and\s+tax\s+statement\b"`
   - 1099-DIV: `r"\b1099[\s-]?div\b"`, `r"\bdividend.*distribution"`
   - 1099-INT: `r"\b1099[\s-]?int\b"`, `r"\binterest\s+income\b"`
   - 1099-MISC: `r"\b1099[\s-]?misc\b"`
   - 1099-NEC: `r"\b1099[\s-]?nec\b"`
   - 1099-B: `r"\b1099[\s-]?b\b"`
   - K-1: `r"\bschedule\s+k[\s-]?1\b"`, `r"\bpartner['\u2019]s\s+share"`
   - engagement: `r"\bengagement\s+letter\b"`
   - organizer: `r"\borganizer\b"`
</action>

<acceptance_criteria>
- File compiles with python -m py_compile
- All 9 DocType values present
- All 12 regex patterns present in _CLASSIFY_RULES
</acceptance_criteria>

### 2. classify() with confidence

**Wave:** 1
**Depends on:** Task 1
**Files modified:** `src/document_classifier.py`

<read_first>
- src/document_classifier.py (just-written enums + rules)
- samples/w2-sample-001.txt (expected doc-type signal density)
</read_first>

<action>
Implement `classify(text: str) -> tuple[DocType, float]`. The function:

1. Returns `(DocType.UNKNOWN, 0.0)` for empty/whitespace-only text.
2. Iterates `_CLASSIFY_RULES`, counts matches per rule.
3. For each rule with count > 0: confidence = `min(0.7 + 0.08 * (count - 1), 0.95)` (single hit yields 0.7; matches in same form boost by +0.08 each up to 0.95 cap).
4. Returns the (DocType, confidence) pair with the highest confidence (tie-break: first matched rule).
</action>

<acceptance_criteria>
- classify("Form W-2 ... Box 1 wages $50,000.00") returns (DocType.W2, >=0.7)
- classify("") returns (DocType.UNKNOWN, 0.0)
- classify(open('samples/1099-div-sample-001.txt').read())[0] == DocType.FORM_1099_DIV
- classify(open('samples/k1-sample-001.txt').read())[0] == DocType.K1_PAGE1
- classify(open('samples/unknown-sample-001.txt').read())[0] == DocType.UNKNOWN
</acceptance_criteria>

### 3. Field extractor (regex-tolerant)

**Wave:** 1
**Depends on:** Task 2
**Files modified:** `src/document_classifier.py`

<read_first>
- src/document_classifier.py (the classify() function above)
- samples/w2-sample-001.txt (real W-2 form layout to test against)
- samples/1099-div-sample-001.txt
- samples/k1-sample-001.txt
</read_first>

<action>
Add helpers + ExtractedField/ExtractedDocument dataclasses + per-form extractors:

1. `@dataclass class ExtractedField:` with fields `(value: Any, confidence: float, source: str, notes: str | None = None)`.
2. `@dataclass class ExtractedDocument:` with `(doc_type, document_id, classification_confidence, fields, raw_text_hash, extracted_at, extracted_by)` plus a `to_dict()` that converts enums.
3. `_parse_money(s)` — strip $, comma, parse float, return None on failure.
4. `_extract_after_label(text, label_pattern, value_pattern)` — find the label regex match, scan the next 400 chars (line-wrap tolerant) for a money-like token; fall back to first number; return stripped string.
5. Per-form extractors `_extract_w2(text)`, `_extract_1099_div(text)`, `_extract_1099_int(text)`, `_extract_1099_b(text)`, `_extract_k1(text)`:
   - W-2: box1_wages ($75k sample), box2_federal_withheld ($11.25k), box3_ss_wages, box4_ss_withheld, employer_ein (12-3456789).
   - 1099-DIV: box1a_ordinary_dividends ($4250), box1b_qualified_dividends ($3200), payer_tin (98-7654321).
   - 1099-INT: box1_interest ($1250).
   - 1099-B: box1a_description (text), box2_proceeds.
   - K-1: part3_line1_ordinary_income ($125000), part3_line5_interest ($5200), partner_share_pct (50).
6. `extract_document(text, doc_type=None, document_id=None)` — compute SHA-256 of text → doc_id like `doc-<16hex>`; classify if doc_type not given; dispatch to right per-form extractor; emit default confidences 0.7-0.9 per field.
</action>

<acceptance_criteria>
- Box 1 wages for synthetic W-2 returns 75000.0 ± $0.01
- employer_ein returns "12-3456789"
- box1a_ordinary_dividends returns 4250.0 ± $0.01
- payer_tin returns "98-7654321"
- partner_share_pct returns 50.0 ± 0.001
- part3_line1_ordinary_income returns 125000.0 ± $0.01
- Same input text yields same document_id (idempotent)
</acceptance_criteria>

### 4. Pytest: 8 classify/extract tests

**Wave:** 1
**Depends on:** Task 3
**Files modified:** `tests/test_classifier_router.py`

<read_first>
- samples/*.txt (real synthetic form text)
- src/document_classifier.py (the API)
</read_first>

<action>
Create `tests/test_classifier_router.py` with these 8 tests in this section, all using `pytest`-style asserts:

1. `test_classify_w2` — assert doc_type == W2 and confidence >= 0.7
2. `test_classify_1099_div` — same for 1099-DIV sample
3. `test_classify_1099_int` — same for 1099-INT sample
4. `test_classify_k1` — same for K-1 sample
5. `test_classify_unknown` — unknown sample returns DocType.UNKNOWN
6. `test_classify_empty` — classify("") returns (UNKNOWN, 0.0)
7. `test_extract_w2_finds_box1_and_ein` — value checks for box1_wages + employer_ein
8. `test_extract_1099_div_finds_box1a_and_payer_tin` — value checks for box1a + payer_tin
9. `test_extract_k1_finds_partner_share_and_line1` — value checks for partner_share_pct + part3_line1
10. `test_extract_is_idempotent_same_text_same_doc_id` — same text → same document_id

Each test imports via `sys.path.insert(0, str(Path(__file__).parent.parent / "src"))` to locate the module.
</action>

<acceptance_criteria>
- `pytest tests/test_classifier_router.py -v` runs all 10 tests in this section
- All 10 tests in this section pass
- 0 test failures (Pytest's `min(0.7 + 0.08 * 0) = 0.7` baseline covers the >=0.7 assertion; sample signals are rich enough to hit >=0.7)
</acceptance_criteria>

## Verification

```bash
PYTHONPATH=src pytest tests/test_classifier_router.py -v -k "classify or extract"
# Expect: 10 tests in this phase passing
```

## Out of scope for this phase

- Real OCR (Tesseract + PaddleOCR) — see OUT_OF_SCOPE.md item 1
- LLM-based extraction — see OUT_OF_SCOPE.md item 2
- Per-form prompt YAML — see OUT_OF_SCOPE.md item 2
