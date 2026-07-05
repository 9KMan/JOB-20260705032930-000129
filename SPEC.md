# SPEC: Senior Automation Engineer — CPA / Tax Workflow Integration Platform

**Job ID:** JOB-20260705032930-000129
**Posted:** 2026-07-04 11:29 UTC (Upwork)
**Client:** CPA firm / Tax practice (Worldwide, ongoing)
**Tier:** EXPERT · Hourly $15–$60/hr · >30 hrs/wk · >6 months
**Engagement:** Ongoing — recurring, portfolio-building

---

## 1. Business Problem Solved

CPA/tax firms burn an extraordinary amount of partner and senior-staff time on work that is **mechanical, repeatable, and well-suited to automation** — particularly:

- Triaging 5,000+ tax documents per season (W-2s, 1099s, K-1s, brokerage statements)
- Copying the same numbers between CCH Axcess, OneSource, ProConnect, and spreadsheets
- Re-keying client-onboarding answers into firm CRM (Karbon, Practice CS, Canopy)
- Hand-routing exception items ("missing signature," "estimated TIN," "wrong entity")
- Generating organizer emails, follow-ups, and status updates
- Producing weekly progress reports for partners from workflow events
- Reviewing AI-extracted structured data against the source PDF for sanity

The client wants to stop paying senior accountants to do this. They want **production-grade workflow automation** that:

1. **Captures** documents from email, SharePoint, and the firm portal
2. **Extracts** structured data with OCR + AI (LLM + small models)
3. **Reconciles** extracted fields against prior years and master records
4. **Routes** to the right preparer/system based on rules + LLM classification
5. **Surfaces exceptions** to humans with full context, not raw "broken" PDFs
6. **Logs everything** for audit + retrospective debugging + IRS defensibility

The wrong way to do this is "build a RAG chatbot." The right way is **event-driven, idempotent, idempotently-replayable workflows** with humans in the loop at the precise points where human judgment matters.

This deliverable is the **foundation**: a deployable, extensible automation platform that the firm can grow into over the next 6+ months.

---

## 2. Functional Requirements

### Phase 1 — Document Intake & Classification (foundation)
- **FR-1.1** Email-to-intake pipeline (Microsoft Graph API webhook → PDF/email body capture)
- **FR-1.2** SharePoint / OneDrive for Business folder watcher (Microsoft Graph delta query)
- **FR-1.3** Firm portal upload endpoint (S3-compatible MinIO with signed URLs)
- **FR-1.4** File-type classifier (W-2, 1099-***, K-1, brokerage, engagement letter, organizer, misc)
- **FR-1.5** Storage-routing rules per type (e.g., W-2 → `tax-prep/{client_id}/{tax_year}/w2/{filename}`)

### Phase 2 — Structured Extraction
- **FR-2.1** OCR engine (Tesseract 5 + PaddleOCR ensemble, GPU-optional)
- **FR-2.2** LLM field extractor (Claude Sonnet / GPT-4o with structured-output JSON schema)
- **FR-2.3** Per-form-type prompts + JSON schemas (W-2, K-1, 1099-DIV/INT/MISC/NEC/B/R, brokerage 1099-B consolidated, organizer forms)
- **FR-2.4** Confidence scoring per field (rule-based + LLM-self-reported)
- **FR-2.5** Cross-year reconciliation (compare this-year field against last-year value; flag deltas > X%)
- **FR-2.6** Manual-review queue for low-confidence extractions (UI + email alerts)

### Phase 3 — Routing & Workflow Engine
- **FR-3.1** Rule-based router (YAML config: type → queue/preparer/service)
- **FR-3.2** LLM-based exception router (low-confidence or unusual pattern → senior reviewer queue)
- **FR-3.3** Idempotent event processing (PostgreSQL outbox pattern + dedupe by document hash)
- **FR-3.4** Webhook fanout to external systems (CCH Axcess API, Karbon CRM, internal Slack/Teams)
- **FR-3.5** Retry with exponential backoff + dead-letter queue for failed routings

### Phase 4 — Client Communication & Organizers
- **FR-4.1** Organizer generator (LLM-assisted packet assembly from prior-year + intake answers)
- **FR-4.2** Email-draft automation (LLM drafts review-needed emails; staff approves before send)
- **FR-4.3** Reminder cadence rules (configurable per client / per engagement)
- **FR-4.4** Two-way email parsing (reply → update job state)

### Phase 5 — Review Tools (AI-assisted, NOT AI-replacing)
- **FR-5.1** Side-by-side PDF + extracted-JSON viewer (Streamlit)
- **FR-5.2** Quick-fix UI for field corrections (auto-re-feeds the corrected value into the router)
- **FR-5.3** Batch-approve low-confidence exceptions (with mandatory "reason" field for audit)
- **FR-5.4** Audit log (who approved what, when, why — append-only)

### Phase 6 — Dashboards & Reporting
- **FR-6.1** Per-engagement progress view (Streamlit + Plotly)
- **FR-6.2** Exception funnel ("1,200 docs in, 18 exceptions, 0 blocked on staff", etc.)
- **FR-6.3** Tax-season-week heatmap (workload visualization for partners)
- **FR-6.4** Power BI semantic model export (CSV/Parquet → OneLake-friendly)

### Phase 7 — Reusable Component Library
- **FR-7.1** Connector SDK (auth pattern: OAuth, API key, OBO for MS Graph)
- **FR-7.2** Pre-built connectors: Microsoft 365 (mail, calendar, files, Teams, SharePoint), CCH Axcess (with documented limits), Karbon CRM, Slack, Outlook SMTP, Twilio (SMS)
- **FR-7.3** Audit-trail helper (append-only `audit_events` table + REST query)
- **FR-7.4** Typed-config loader (Pydantic Settings + YAML)
- **FR-7.5** Deployment templates (Docker Compose for local, Helm chart for Azure AKS)

---

## 3. Non-Functional Requirements

### Security & Compliance (regulated industry)
- **NFR-SEC-1** **All PII must stay in client-controlled infrastructure.** Firm chooses the Azure tenant; we deploy inside it. No exfil to our infrastructure.
- **NFR-SEC-2** Field-level encryption (AES-GCM via Azure Key Vault) for TIN, SSN, account numbers, dependents' names.
- **NFR-SEC-3** Append-only audit log; 7-year retention aligns with IRS recordkeeping (IRC § 6001/6501).
- **NFR-SEC-4** OAuth 2.0 OBO flow for Microsoft Graph (no stored user credentials).
- **NFR-SEC-5** LLM providers must be **Azure OpenAI Service** or **client-approved Anthropic** — NOT consumer endpoints.
- **NFR-SEC-6** SOC 2 considerations: change-control via Git, secret rotation playbook, RBAC.

### Reliability
- **NFR-REL-1** Idempotent event processing — duplicate webhook delivery cannot double-route a document.
- **NFR-REL-2** Retry with exponential backoff, max 5 attempts, dead-letter queue (MinIO `dlq/` bucket).
- **NFR-REL-3** Circuit breaker on external-system failures (CCH Axcess outage shouldn't block intake).
- **NFR-REL-4** Health endpoints (`/health`, `/ready`, `/metrics`) for k8s/Azure Container Apps.

### Observability
- **NFR-OBS-1** Structured JSON logs to stdout (Loki / Azure Log Analytics friendly).
- **NFR-OBS-2** OpenTelemetry traces across intake → extraction → routing.
- **NFR-OBS-3** Per-stage metrics: docs/min, exceptions/rate, OCR-p95-Latency, LLM-tokens/doc, $/1000-docs.
- **NFR-OBS-4** Daily partner digest (Telegram or email) at 07:00 local with prior-day funnel numbers.

### Performance
- **NFR-PERF-1** OCR + extraction **p95 latency ≤ 25 seconds per document** (single-doc mode).
- **NFR-PERF-2** Batch throughput: ≥ 50 documents/minute sustained on a 4-core/8GB worker.
- **NFR-PERF-3** Webhook response time ≤ 2 seconds (push heavy work to background queue).

### Maintainability
- **NFR-MAINT-1** All connectors typed (Pydantic), no raw dicts crossing API boundaries.
- **NFR-MAINT-2** Test coverage ≥ 80% for routing + extraction logic (not infra glue).
- **NFR-MAINT-3** "Run the system offline" mode: `docker compose up` should boot the entire stack on a dev laptop with no Azure dependency.
- **NFR-MAINT-4** GitOps deploy — all config in repo, every change reviewed.

---

## 4. Architecture (Style C — Data Pipeline / ETL — appropriate for an event-driven document workflow)

```
                                                    ┌──────────────────────┐
                                                    │   Partner / Staff    │
                                                    │   Web UI (Streamlit) │
                                                    │   Email / Teams      │
                                                    └──────────┬───────────┘
                                                               │
            ┌──────────────────────────────────────────────────┼────────────────┐
            │                                                  │                │
   ┌────────▼────────┐  ┌──────────────────┐  ┌────────────────▼───┐  ┌────────▼─────────┐
   │  Email + Share  │  │  Firm Portal     │  │   Approval /       │  │   Dashboard      │
   │  Webhooks       │  │  Upload API      │  │   Review UI         │  │   Streamlit +    │
   │  (MS Graph)     │  │  (MinIO S3 API)  │  │   (FR-5.1/5.2)      │  │   Power BI expt  │
   └────────┬────────┘  └────────┬─────────┘  └────────┬───────────┘  └────────┬─────────┘
            │                    │                     │                       │
            └────────────────────┼─────────────────────┘                       │
                                 │                                             │
                  ┌──────────────▼──────────────┐                              │
                  │   Message Bus (Redis or     │                              │
                  │   RabbitMQ) — durable queue │                              │
                  └──────────────┬──────────────┘                              │
                                 │                                             │
        ┌────────────────────────┼────────────────────────┐                    │
        │                        │                        │                    │
   ┌────▼─────────┐      ┌───────▼─────────┐      ┌──────▼─────────┐         │
   │ Intake       │      │  Extractor       │      │  Router        │         │
   │ Worker       │      │  Worker          │      │  Worker        │         │
   │ (FR-1.*)     │      │  (FR-2.*)        │      │  (FR-3.*)      │         │
   │ classify +   │      │  OCR + LLM       │      │  rules + LLM   │         │
   │ store raw    │      │  JSON schema     │      │  CCH/Karbon/   │         │
   └────┬─────────┘      └────┬─────────────┘      │  Slack fanout  │         │
        │                     │                    └──────┬─────────┘         │
        └──────────┬──────────┘                           │                   │
                   │                                      │                   │
            ┌──────▼──────────┐                  ┌───────▼────────┐           │
            │  MinIO          │                  │  External      │           │
            │  (S3-API)       │                  │  Systems       │           │
            │  ┌───────────┐  │                  │  • CCH Axcess  │           │
            │  │ documents │  │                  │  • Karbon CRM  │           │
            │  └───────────┘  │                  │  • Slack/Teams │           │
            │  ┌───────────┐  │                  │  • SMTP        │           │
            │  │ extracted │  │                  │  • Twilio SMS  │           │
            │  └───────────┘  │                  └────────────────┘           │
            │  ┌───────────┐  │                                              │
            │  │ dlq/      │  │                                              │
            │  └───────────┘  │                                              │
            └─────────────────┘                                              │
                                                                             │
                  ┌──────────────────────────────────────────────────────────┘
                  │
           ┌──────▼───────┐
           │  Audit Log   │ — append-only, ≥7 yr retention
           │  (Postgres)  │
           └──────┬───────┘
                  │
           ┌──────▼───────┐
           │  Postgres    │
           │  ┌─────────┐ │
           │  │ jobs    │ │ — workflow state, retry counters, idempotency keys
           │  │ events  │ │
           │  │ audit_  │ │
           │  │ events  │ │
           │  └─────────┘ │
           └──────────────┘
```

**Key architectural decisions:**

| Decision | Choice | Why |
|---|---|---|
| Message bus | Redis Streams (default) → upgradeable to RabbitMQ | Redis gives us durable streams + consumer groups with simpler ops; can swap for RabbitMQ later if fanout bursts |
| Object storage | MinIO (S3 API) | Runs anywhere; client can swap for Azure Blob with same code |
| LLM provider | Azure OpenAI Service (primary); Claude via Anthropic API if approved | Stays in client tenant; SOC 2 friendly |
| Frontend | Streamlit (Phase 1) | Fastest for staff tools; can graduate to Next.js |
| Database | PostgreSQL 16 | Audit-log, JSON storage, idempotency keys, full-text search |
| Deploy | Docker Compose (dev) + Azure Container Apps (prod) | Low-ops start; client-tenant-ready |

---

## 5. Tech Stack

| Category | Technologies |
|---|---|
| Languages | Python (primary), TypeScript (UI connectors), SQL |
| Frameworks | FastAPI (API), Streamlit (UI), Celery (background), Pydantic (typed config/models) |
| Databases | PostgreSQL 16, Redis 7, MinIO |
| AI/ML | Azure OpenAI Service (GPT-4o), Anthropic Claude, Tesseract 5, PaddleOCR, sentence-transformers |
| Integrations | Microsoft Graph API (mail/files/calendar), SharePoint REST, CCH Axcess (where API available), Karbon CRM, Slack, Outlook SMTP, Twilio |
| Automation | n8n (preferred for non-engineers), Power Automate (if client uses it), internal FastAPI workflows |
| Cloud | Azure (primary), AWS (alternative), Azure Container Apps, Azure Key Vault |
| Infra | Docker, Docker Compose, Helm chart for AKS, GitHub Actions CI |
| Observability | OpenTelemetry, structlog, Loki + Grafana (or Azure Monitor), Sentry |
| Security | OAuth 2.0 (MSAL), Pydantic validators, AES-GCM (cryptography lib), Azure Key Vault SDK |

---

## 6. Out of Scope (explicit)

Per the spec — these are **NOT** in this build:

1. **Filing actual tax returns** — the firm retains judgment on returns. We automate the data pipeline; staff review.
2. **IRS e-file direct integration** — out of compliance scope; firm uses their existing CCH/PRO system.
3. **Client-facing mobile app** — desktop/email only for v1.
4. **Document retention/disposal automation** — manual review; we provide hooks.
5. **Custom hardware/scanner integration** — scan-to-email covers 95% of cases.
6. **Audit-defensible AI-extracted numbers** — final review by human is mandatory in jurisdiction.
7. **Replacement of any existing system** — additive integration only (the firm keeps CCH/PRO/Karbon as source of truth).

---

## 7. Implementation Plan (12-week milestones)

| Week | Milestone | Deliverables |
|---|---|---|
| 1–2 | **Foundation** | GitHub repo + Azure tenant setup, MinIO/Postgres/Redis booted, FastAPI scaffold, MS Graph OAuth flow, intake worker stub |
| 3–4 | **Document Intake** | Email webhook + SharePoint delta + portal upload — all three pipelines ingesting to MinIO + classifier producing a type label |
| 5–6 | **Extraction** | OCR (Tesseract + PaddleOCR) + LLM JSON extraction for 3 highest-volume forms: W-2, 1099-DIV, K-1 (page 1) |
| 7–8 | **Routing + Audit** | Rule-based router + LLM exception router + idempotency keys + audit_events append-only |
| 9–10 | **Review UI + Email automation** | Streamlit review viewer + email-draft LLM + organizer packet generator |
| 11–12 | **Dashboards + Connectors** | Streamlit partner dashboard + 4 more pre-built connectors (Karbon, Slack, SMTP, Twilio) + Helm chart |

**Maintenance cadence (post-12-week):** weekly check-in, monthly metrics report, quarterly roadmap refresh.

---

## 8. Pricing & Engagement Model

**Rate:** $60/hr (within posted $15–60/hr band, top of range for EXPERT-tier fit)
**Hours:** 30–40/week
**Engagement:** ongoing, evaluated quarterly
**Trial:** first 4 weeks at $50/hr discounted; convert to $60/hr on KPI confirmation

**Why not lower:** candidate chose to underprice CPA/tax domain in this last batch — top-tier rates signal seriousness about regulated work + retain weekly capacity.

---

## 9. Acceptance Criteria

1. ✅ `docker compose up` boots the full stack on a clean dev laptop within 10 minutes.
2. ✅ All three intake sources (email, SharePoint, portal) deliver a sample document to MinIO with type classification in <2 minutes.
3. ✅ OCR + extraction produces valid JSON for W-2, 1099-DIV, K-1 (page 1) with ≥90% field accuracy against the partner-reviewed gold set.
4. ✅ Cross-year reconciliation flags a >5% delta as an exception.
5. ✅ Rule router sends a known W-2 to the right preparer queue without manual intervention.
6. ✅ LLM exception router correctly flags malformed/unusual docs to senior reviewer queue.
7. ✅ Manual review UI lets staff override a field; the override is logged in audit_events.
8. ✅ Email-draft automation produces a review-needed email; staff clicks Approve to actually send.
9. ✅ Streamlit dashboard shows the day's funnel numbers refreshed within 5 minutes.
10. ✅ Audit log captures every stage-transition with actor + timestamp + reason for ≥7 years.
11. ✅ ≥80% test coverage on routing + extraction logic.
12. ✅ Helm chart deploys the stack to Azure Container Apps in <30 minutes.

---

## 10. Privacy & Data Residency

- All data lives in **client's own Azure tenant**; we deploy there. No exfil to our infrastructure.
- LLM calls go to **client's Azure OpenAI Service** instance, not our endpoints.
- Field-level encryption uses client's **Azure Key Vault**.
- We have **no standing access** to client data once deployed; access is via emergency break-glass with full audit trail.
- BAA / MSA covered by client's standard professional services agreement.

---

## 11. Deliverables

- GitHub repo with full source + tests + Helm chart
- Architecture diagram (this doc, Section 4)
- Run-book for partner-led ops
- Quarterly roadmap / metrics review
- Connectors library (Microsoft Graph, SharePoint, Karbon, CCH Axcess [where API allowed], Slack, SMTP, Twilio)
- 30+ days post-delivery support included
