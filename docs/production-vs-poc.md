# Production vs PoC — what changed and why

This document explains the production artifacts in the repository root and the
`deploy/` and `helm/` directories, and how they relate to the PoC shipped under
`src/`, `tests/`, and the `.planning/phases/` decision-driven plan set.

## TL;DR

The PoC under `src/` answers: "can we classify and route a W-2 / 1099 / K-1
correctly enough to ship?" The production artifacts in this directory answer:
"how does this run as a service that an audit firm would sign off on?"

The 5 decision-driven phases from the PoC map 1:1 to production concerns:

| PoC phase (decision) | Production realization |
|---|---|
| 01-classifier-baseline | `src/classifier.py` heuristic + LLM model. Containerized. |
| 02-router-confidence | `src/router.py` + helm `Deployment` + ACA autoscale 2→10 pods. |
| 03-audit-immutability | `src/audit.py` + `deploy/azure-container-apps.bicep` immutable WORM blob. |
| 04-intake-idempotency | `src/idempotency.py` + Postgres unique constraint + ingress `max-body-size: 20m`. |
| 05-reviewer-workflow | `src/reviewer.py` + Entra ID app registration via `AZURE_CLIENT_ID`. |

## What the PoC deliberately does NOT include

For the full deferral list see `OUT_OF_SCOPE.md`. The short version: the PoC
is runnable on a developer laptop and answerable in a single conversation.
The production artifacts are a parallel portfolio layer showing what a real
deployment would look like, not a replacement for the PoC.

## Production artifacts

### Container artifacts (root level)

| File | Purpose |
|---|---|
| `Dockerfile.production` | Multi-stage, non-root, distroless runtime. The PoC uses `Dockerfile` (single-stage, dev-friendly). |
| `requirements.production.txt` | Pinned prod deps + the runtime extras (`gunicorn`, `psycopg2-binary`, `redis`, `azure-identity`, `azure-storage-blob`, `msgraph-sdk`). |
| `docker-compose.production.yml` | Local-prod parity: Postgres + Redis + MinIO + the app, with healthchecks. Not for prod deploy. |

### Kubernetes manifests (helm/cpa-doc-intake/)

Production-targeted Helm chart. Renderable: `helm template test helm/cpa-doc-intake/`
yields 9 resources (CM, Secret, SA, Deployment, Service, Ingress, HPA, PDB, NetworkPolicy).

- **Decision: 02-router-confidence** — Deployment with rolling updates, HPA 2→10 pods.
- **Decision: 03-audit-immutability** — PodDisruptionBudget (minAvailable=1) so audit pipeline is never dropped during voluntary disruption.
- **Decision: 04-intake-idempotency** — Ingress with `proxy-body-size: 20m` for big PDFs.
- **Defense in depth** — readOnlyRootFilesystem, runAsNonRoot, seccomp=RuntimeDefault, all caps dropped.
- **Secrets via CSI driver** — `secretProviderClass: cpa-key-vault-secrets`. Real credentials never enter the chart.

### Azure infrastructure (deploy/)

- `azure-container-apps.bicep` — full ACA environment, Postgres Flexible Server,
  Redis, Storage Account with WORM-immutable audit container, and the API app
  bound to workload identity. Parameterized for partner-specific values.
- `modules/managed-cert.bicep` — conditional managed certificate for custom domain.
- `otel-collector-config.yaml` — OpenTelemetry Collector config: OTLP receivers,
  memory limiter, batching, resource attributes. Tuned for the CPA workload
  (drops healthcheck metrics to control cardinality).

### Configuration (.env.production.example)

Reference config showing every env var the app reads. Real values come from
Azure Key Vault via workload identity; this file only documents resource
identifiers and decision flags.

## How a partner engagement would consume this

```
1. Partner provides: tenant ID, subscription, region, custom domain (optional).
2. We run:       az deployment group create \
                    --template-file deploy/azure-container-apps.bicep \
                    --parameters namePrefix=<prefix> uamiClientId=... tenantId=... msGraphClientId=...
3. We run:       kubectl apply -f SecretProviderClass.yaml   # binds KV secrets to CSI
4. We run:       helm upgrade --install cpa-intake helm/cpa-doc-intake/ \
                    --set image.tag=<sha> \
                    --set azureOpenai.endpoint=... \
                    --set postgres.host=... \
                    --set redis.host=...
5. We verify:    helm test cpa-intake
                 (or the e2e_smoke.sh script run against the ACA FQDN)
```

Total time-to-prod for a CPA firm: roughly 1 day if the Azure tenant is already
set up, 3-5 days if Entra ID app registration needs to be wired from scratch.

## Why the production artifacts live alongside the PoC

The PoC under `src/` is the artifact the partner would evaluate for *correctness*
("does the classifier actually route W-2s to the preparer queue?"). The
production artifacts here are the artifact they would evaluate for *deployability*
("can we run this without a 3-week DevOps engagement?").

A senior reviewer at a 50-partner firm asks both questions. Showing both
answers — and showing that they came from the same decision-driven plan set —
is the "Built Before Bid" signal that justifies the bid.

## Cross-references

- `.planning/JOB-129-POC-SCOPE.md` Appendix B — production-build phase map.
- `OUT_OF_SCOPE.md` — 11 features deferred from PoC, mapped to production artifacts here.
- `.planning/phases/01..05/PLAN-01.md` — the 5 decision-driven GSD plans.
- `scripts/validate_gsd_plans.py` — validates plan structure + decision coverage.