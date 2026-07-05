.planning/JOB-129-POC-SCOPE.md
=====================
Phase plan + scope for the Job-129 (Senior Automation Engineer — CPA / Tax
Workflow Integrations) PoC build.

## Context

Job ID: JOB-20260705032930-000129
Posted: 2026-07-04 (9 hours before intake, 50+ proposals already)
Client: CPA firm / Tax practice (EXPERT tier, >30 hrs/wk, >6 months,
$15-60/hr; willing to pay higher for fit)
Routing decision: BID $60/hr (top of band, EXPERT-tier signal) + $50/hr
× 4 weeks trial discount.

## Build strategy: "built-before-bid" PoC

Jobs 130/131/132 set the pattern (fact #42, #45): for a high-volume
proposal queue, ship a working PoC that demonstrates the actual
architecture end-to-end so the proposal stands out from non-technical
bidders. Skip the full production system; build a local-runnable PoC
that proves the architecture, data model, and routing logic before any
of the heavy infra (Tesseract OCR, LLM JSON extraction, MS Graph
webhooks, Postgres audit, Azure Container Apps deploy).

## Phases

The PoC is one shipping unit. We do not split into the 7-phase GSD
schedule that the production build would use — too much overhead for
a 30-minute single-shot. Instead, we record here the 4 logical blocks
that the PoC proves out, plus the 5 production blocks that would be
needed beyond it.

### Block A (PoC) — Classifier

Files: src/document_classifier.py
Output: DocType enum + ExtractedDocument dataclass + classify() and
extract_document() functions.
Acceptance:
- classify() returns (DocType, conf >= 0.7) for W-2/1099-DIV/1099-INT/1099-B/K-1
- extract_document() pulls Box 1 wages + EIN for W-2 to within $0.01
- 18 pytest tests cover classify/extract for 5 form types + Unknown + idempotency

### Block B (PoC) — Router + Audit

Files: src/router.py
Output: RoutingRule dataclass + Route enum + DEFAULT_RULES +
route_document() + audit append.
Acceptance:
- route_document() returns Route.PREPARER_QUEUE for high-confidence
  W-2 / 1099-* / 1099-B
- Returns Route.SENIOR_REVIEWER for K-1 / engagement / organizer / unknown
- Demotes from preparer to senior when any field confidence < 0.7
- Every routing decision appends to /tmp/poc-audit-log.jsonl with
  {ts, doc_id, actor, event_type, payload}

### Block C (PoC) — Intake Worker

Files: src/runner.py
Output: Idempotent file-watcher. Reads docs/inbox/*.txt, classifies,
extracts, routes, writes extracted JSON to docs/extracted/<doc_id>.json.
Acceptance:
- Re-running on already-processed files is a no-op
- Idempotency key is SHA-256 of file content
- Errors land in docs/dlq/ instead of crashing the worker

### Block D (PoC) — Review UI

Files: src/ui.py
Output: Streamlit UI showing side-by-side raw text + extracted JSON,
with field-level confidence highlighting + one-click Approve / Override
(with reason capture).
Acceptance:
- Pipeline summary appears in sidebar
- Senior reviewer queue shows count of low-confidence docs
- Approval writes an audit_event with actor=senior-reviewer-poc
- Override requires a reason text (logged)

### Production phases (out of scope for this PoC)

Phase 1 (Foundation): repo + Azure tenant + intake stub (real MS Graph OAuth).
Phase 2 (Intake): email + SharePoint delta + portal S3 signed URL.
Phase 3 (Extraction): Tesseract 5 + PaddleOCR ensemble + Azure OpenAI
Service per-form JSON schemas + cross-year delta checks.
Phase 4 (Routing): YAML config table + LLM exception classifier +
Postgres jobs table + idempotency index.
Phase 5 (UI + Email): Organizer packet generator + email-draft LLM +
Streamlit viewer deployed to Azure.
Phase 6 (Connectors + Deploy): 4+ pre-built connectors + Helm chart +
Azure Container Apps profile + GitHub Actions CI.

## Tradeoff: scope vs time-to-bid

This PoC touches a fraction of the production system but proves:
1. The classifier handles real-world form text (not just regex toy)
2. The router respects confidence thresholding
3. Idempotency is in place so double-delivered webhooks won't double-route
4. Audit log is append-only with required actor + ts
5. Streamlit UI is one page that works

That is enough to win the "real engineer, not slideware" signal in the
Upwork proposal queue.

## Why we bypassed GSD for the build itself

- gsd-build.py is multi-week-phase oriented; 30-min PoC doesn't fit
- subagent timeouts (fact #46) made delegation unreliable for code-write
- Bug #2 still under observation; not worth relying on the new
  filesystem-diff fallback for a 30-min single-shot
- The triple-fallback in gsd-execute-plan.py:894-905 is unproven on
  coding-agent path post-Bug-211

For the 12-week production build, we would absolutely reroute through
gsd-build.py with PLAN-01.md per phase. We are explicitly deferring that
to the engagement phase.
