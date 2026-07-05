# OUT_OF_SCOPE — CPA Document Intake Pipeline (PoC)

This document enumerates features that are **deliberately** excluded
from this PoC. Every entry below is paired with a code reference that
demonstrates the deferment — typically a stub that explicitly raises a
"not in PoC" indicator, or a comment block in the source.

> **Process:** When the production build adds an OUT_OF_SCOPE item
> (i.e., swaps the PoC stub for the real implementation), it must
> (a) remove the section here, (b) replace the stub with the real code,
> and (c) update `tests/test_classifier_router.py` if the contract
> changes.

---

## OCR pipeline (Tesseract + PaddleOCR ensemble)

The current `extract_document` and `classify` functions run on the
text directly. The PoC assumes the document is already text — the
input is `.txt` files in `docs/inbox/`. In production we need to read
PDFs (and possibly scanned TIFFs) before we can classify or extract.

The production build will swap `src/runner.py`'s `_read_text()` for
a Tesseract 5 + PaddleOCR ensemble with confidence-weighted voting.
The current stub simply reads the file as text.

**Code reference:** `src/runner.py:36` (`_read_text`) returns the raw
bytes-as-utf8 for any extension. PDF/iTIFF inputs would currently
fail to decode or return garbage.

---

## LLM JSON extraction (Azure OpenAI Service with structured outputs)

The current `_extract_w2`, `_extract_1099_div`, etc. functions are
pure regex over the synthetic sample text. Production needs real LLM
extraction with per-form JSON schemas, confidence self-reporting, and
cross-year delta reconciliation against prior-year extracted data.

The production build will swap the `_extract_*` family of functions
for Claude Sonnet / GPT-4o calls with `response_format={"type":
"json_schema"}` and per-form prompts from a YAML config.

**Code reference:** `src/document_classifier.py:_extract_w2`
(documented inline as `poc-regex-v0`). Production swap point is the
function body.

---

## Microsoft Graph + SharePoint delta + portal S3 webhook intake

The current runner polls `docs/inbox/` for `.txt` files. Production
needs three live intake sources:
- Microsoft Graph webhook on `/me/messages` (email)
- SharePoint REST delta query on the firm site (file docs)
- MinIO/S3 signed-url upload endpoint on the firm portal (client uploads)

Each requires OAuth 2.0 OBO flow against the firm's Azure tenant.

**Code reference:** `src/runner.py:8-22` (`INBOX = REPO_ROOT / "docs" / "inbox"`).
Production swap point is the source of files.

---

## Database-backed idempotency (Postgres `documents` table)

The current idempotency check is a filesystem `_already_processed()`
test that looks for `docs/extracted/<hash>.json`. Production needs
a Postgres `documents` table keyed by SHA-256 with audit columns
(`classified_at`, `classified_by`, `routed_at`, `routed_to`).

**Code reference:** `src/runner.py:_already_processed` (filesystem
check). Production swap point is the same function.

---

## Postgres append-only audit log with 7-year retention (IRC §6001)

The current audit log is a JSONL file at `/tmp/poc-audit-log.jsonl`.
Production needs a Postgres `audit_events` table with `BEFORE UPDATE`
and `BEFORE DELETE` triggers enforcing immutability, and a 7-year
retention policy aligned with IRS recordkeeping requirements.

**Code reference:** `src/router.py:_AUDIT_LOG_PATH` (file path).
Production swap point is the `append_audit_event` body and storage target.

---

## Streamlit auth + multi-tenant support

The current `src/ui.py` has no authentication and renders any extracted
doc to any user who can reach the URL. Production needs:
- OpenID Connect against the firm's Microsoft tenant
- Per-firm / per-user filtering of the senior reviewer queue
- Role-based access (preparer vs senior reviewer vs partner)

**Code reference:** `src/ui.py` has no auth decorator; the page renders
to all callers.

---

## Real LLM-based exception router

The current `src/router.py` is purely rule-based + regex-extraction
demotion. Production needs an LLM exception classifier — when a doc
looks unusual (low confidence across many fields, or unusual form
content), the LLM classifies *why* and routes to the right specialist
queue (K-1 partnership, estate & trust, individual, etc.).

**Code reference:** `src/router.py:DEFAULT_RULES` (static table).
Production adds an `llm_exception_router()` function and calls it
when rule-based confidence falls below threshold.

---

## Cross-year reconciliation engine

The current extractor is stateless — every extraction is independent.
Production needs a weekly reconciliation job that compares this-year's
extracted JSON against last-year's, flagging > 5% deltas to the partner
queue (a sudden change in income or deductions often indicates either
a real life event to discuss in review or an extraction error).

**Code reference:** No reconciliation code exists. New module planned.

---

## Helm chart + Azure Container Apps deploy

`Dockerfile` and `docker-compose.yml` are bootable as a local demo,
but production needs:
- Multi-stage Dockerfile (smaller image, no dev dependencies)
- Helm chart with values.yaml for AKS / Azure Container Apps
- GitHub Actions CI/CD with env-specific config overlays
- TLS termination, ingress, secrets via Azure Key Vault

**Code reference:** `Dockerfile` (POC-shaped, single-stage). Production
swap is a multi-stage rewrite.

---

## Field-level AES-GCM encryption for PII

The current runner logs the full extracted JSON to disk. Production
needs field-level encryption (AES-GCM) for TIN, SSN, account numbers,
dependents' names — encryption keys live in client's Azure Key Vault.

**Code reference:** No encryption code exists; `docs/extracted/*.json`
is plaintext. Production adds an `encrypt_field` wrapper around any
field marked sensitive in the schema.

---

## Multi-region failover for the message bus

The PoC uses Redis Streams as the message bus (single instance).
Production needs RabbitMQ or Azure Service Bus with multi-region
replication, plus circuit breakers on external-system failures
(CCH Axcess outage shouldn't block intake — circuit opens, queued
docs retry when service comes back).

**Code reference:** `src/runner.py` has no bus; it's a single-process
poll. Production adds a Celery worker pulling from Redis Streams
(or RabbitMQ for higher throughput).

---

## Summary

This PoC is a **demonstration of the architecture and core logic**, not
a production system. The above 11 items are the gap between "running
on a laptop with synthetic samples" and "running inside a CPA firm's
Azure tenant processing real W-2s, 1099s, and K-1s."

For the production engagement, **every entry above becomes a deliverable
in the 12-week timeline** documented in SPEC.md Section 7.
