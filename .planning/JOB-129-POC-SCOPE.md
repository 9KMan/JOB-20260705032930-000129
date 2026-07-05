# JOB-129 PoC Scope

**Job ID:** JOB-20260705032930-000129
**Posted:** 2026-07-04 11:29 UTC (Upwork)
**Client:** CPA firm / Tax practice (Worldwide, ongoing)
**Tier:** EXPERT · $15–$60/hr · >30 hrs/wk · >6 months
**Engagement:** Ongoing — recurring, portfolio-building

---

## Why this doc exists

This doc captures **what this PoC proves**, **what it deliberately doesn't prove** (and how production builds it), and **the framing we chose for the planning phases**.

## Plan framing: decision-driven (not universal-7)

The standard `intake-to-review.py` factory pipeline generates a universal 7-phase plan (`1-overview` … `7-ui-ux`) for every job. That's an intake-time convenience and works well for production builds where the codebase IS the product.

This PoC is different: it's a 30-minute single-shot built before bidding, not a multi-week production build. The 7-phase default doesn't honor what this specific job needs — it forces generic phases like "tech stack selection" and "data model" that don't map to a single PoC.

**So we use decision-driven phasing instead.** Each phase answers one explicit decision a CPA firm partner would ask:

| Phase | Decision the phase proves |
|---|---|
| **01-classifier-baseline** | Can we classify real tax forms with PoC-grade logic? |
| **02-router-confidence** | Does the rule router respect confidences without false-trusting low-confidence routing? |
| **03-audit-immutability** | Can we prove every routing decision is captured in an append-only audit log? |
| **04-intake-idempotency** | Can the intake worker process docs WITHOUT double-processing on retry? |
| **05-reviewer-workflow** | Can a senior reviewer actually use the Streamlit UI + does the full pipeline hold together? |

5 phases, 5 decisions, 5 e2e smoke checks. Each phase's `acceptance_decision` field in the YAML frontmatter is the literal pass/fail test.

**Why this works:**
- Each phase is binary: yes-or-no answer to a real engagement question
- The phase ordering matches the data-flow (classify → route → audit → worker → UI)
- Production builds can map each phase to a production-build phase (Appendix B)

**What's lost vs universal-7:**
- No "data model" or "tech stack" phase — those are obvious for a Python+Streamlit PoC
- No "out-of-scope" phase — that lives in `OUT_OF_SCOPE.md` instead
- No "architecture" phase — that's in SPEC.md + `diagrams/architecture.svg`

## What this PoC proves

1. **End-to-end pipeline works**: a sample W-2 arrives in `docs/inbox/`, gets classified (Phase 1), routed (Phase 2), audit-logged (Phase 3), persisted (Phase 4), and surfaces in the review UI (Phase 5).
2. **Idempotency works**: re-running the worker doesn't double-route, doesn't double-bill, doesn't break the audit log.
3. **Confidence gates work**: a low-confidence field forces the doc to senior reviewer regardless of the default rule.
4. **Audit log is structurally compliant**: every event has `ts + doc_id + event_type + actor + payload`, exactly what an IRS-defensible log needs.
5. **The reviewer can ACT, not just observe**: Approve / Override / DLQ buttons all append audit events, Override requires a reason field.

## What this PoC deliberately doesn't prove

Each `## Question this phase answers` above states the single thing the phase proves. Everything else is OUT_OF_SCOPE.md's job to enumerate. The full production-build mapping is in **Appendix B** below.

## How to verify

```bash
cd /home/deploy/squad/build-worker/JOB-20260705032930-000129

# 1. Validator — all 5 plans parse, all listed files exist
. .venv/bin/activate
python3 scripts/validate_gsd_plans.py

# 2. Per-phase acceptance — pytest runs all 20 tests
PYTHONPATH=src pytest tests/ -q

# 3. Phase 4 acceptance — bash scripts/demo.sh proves idempotency
bash scripts/demo.sh

# 4. Phase 5 acceptance — bash scripts/e2e_smoke.sh proves the full chain
bash scripts/e2e_smoke.sh
```

If all four pass: this PoC is ready to ship as the "proof of capability" attached to the Upwork bid.

---

## Appendix B — Production Build Phase Map (12-week engagement)

If this PoC wins the bid and the engagement starts, here's how each decision-driven PoC phase maps to a production-build phase for the 12-week build. The production phases use the universal-7 intake frame because at that point the codebase IS the product (not a PoC).

| PoC phase (decision-driven) | Production build phase (universal-7) | What changes |
|---|---|---|
| 01-classifier-baseline | → Phase 4 (data-model) + Phase 5 (project-structure) — *"OCR pipeline"* | Replace regex with Tesseract + PaddleOCR ensemble + Azure OpenAI Service JSON extraction. Add per-form YAML prompts + structured outputs API. Cross-year delta engine. |
| 02-router-confidence | → Phase 4 (data-model) — *"routing layer"* | Replace hardcoded DEFAULT_RULES with YAML config. Add LLM exception classifier (zero-shot on unusual forms). Per-firm rule customization. |
| 03-audit-immutability | → Phase 4 (data-model) + Phase 6 (out-of-scope) — *"audit_events table"* | Replace `/tmp/poc-audit-log.jsonl` with Postgres `audit_events` (append-only triggers). 7-year retention aligned with IRC § 6001. Field-level encryption via Azure Key Vault. |
| 04-intake-idempotency | → Phase 3 (architecture) + Phase 5 (project-structure) — *"production intake"* | Replace `docs/inbox/` polling with Celery + Redis Streams. Microsoft Graph webhook + SharePoint delta + portal S3 signed URLs. Postgres-backed idempotency index. |
| 05-reviewer-workflow | → Phase 7 (UI/UX) — *"Streamlit → production UI"* | OpenID Connect against firm's Microsoft tenant. Multi-tenant scoping. Streamlit Cloud or Azure App Service deploy. Helm chart for AKS / Azure Container Apps. |

### Risks pinned to production phases (added during engagement)

These are `OUT_OF_SCOPE.md` items that become production-build acceptance criteria, not new phases:

| Risk (from `OUT_OF_SCOPE.md`) | Production phase acceptance test |
|---|---|
| Hallucinated fields from LLM extraction | Phase 4 (data-model): JSON schema validation + per-field confidence threshold + manual review queue for low-confidence |
| PII leaked through logs | Phase 4 (data-model): field-level AES-GCM encryption via Azure Key Vault + log redaction |
| 12-week doc throughput vs scale | Phase 3 (architecture): load test against RabbitMQ + Azure Service Bus for multi-region |
| Compliance audit trail under IRS scrutiny | Phase 4 (data-model): Postgres append-only triggers + 7-year retention alignment with IRC § 6001 |
| CCH Axcess API outage cascading | Phase 3 (architecture): circuit breaker + dead-letter queue + retry-with-backoff |

---

## Appendix A — Why "decision-driven" not "user-story"

We considered four framings before settling on decision-driven:

| Framing | Why it would also work | Why decision-driven wins |
|---|---|---|
| User-story (Sheila the senior reviewer's perspective, David's intake perspective, Maria the partner's perspective) | Maps to client-side concerns; good for marketing | Phases become dependent on multiple components; less useful for build ordering |
| Risk-gated (one phase per `OUT_OF_SCOPE.md` item) | Aligns with what the partner worries about | Phases become paranoid rather than functional; harder to communicate |
| Universal-7 (intake-to-review.py default) | Standard factory convention | Forces generic phases that don't honor a 30-minute PoC's actual shape |
| **Decision-driven (chosen)** | Each phase is a binary answer to a real engagement question | Maps directly to PROPOSAL.md acceptance criteria + each `OUT_OF_SCOPE.md` item gets a phase by name |

## Summary

**Job-129 PoC uses 5 decision-driven phases because that's what this job actually needs.** The factory's universal-7 intake frame remains correct for production builds of full codebases; for PoCs and bespoke engagements, decision-driven phases give clearer acceptance tests and better mapping to the production handoff (Appendix B).
