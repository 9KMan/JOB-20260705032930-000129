# CPA Document Intake — Deployment Guide

This repository ships both a **PoC** (runnable on a developer laptop) and
**production artifacts** (deployable to a CPA firm's Azure tenant).

The PoC is what the partner evaluates for *correctness*.
The production artifacts are what the partner evaluates for *deployability*.

## Repository layout

```
JOB-20260705032930-000129/
|-- src/                          PoC: classification, routing, audit, idempotency, reviewer
|-- tests/                        Pytest suite (20/20 passing)
|-- samples/                      6 synthetic tax documents (W-2, 1099-DIV, 1099-INT, 1099-B, K-1, unknown)
|-- .planning/
|   |-- phases/                   5 decision-driven GSD phases (01..05)
|   |-- JOB-129-POC-SCOPE.md      Framing declaration + production-build phase map
|-- scripts/
|   |-- e2e_smoke.sh              End-to-end smoke test against the PoC
|   |-- validate_gsd_plans.py     Plan validator + decision reporter
|-- deploy/                       Production Azure infrastructure
|   |-- azure-container-apps.bicep
|   |-- modules/managed-cert.bicep
|   |-- otel-collector-config.yaml
|-- helm/cpa-doc-intake/          Production Kubernetes Helm chart (9 resources)
|-- diagrams/                     Architecture + sequence diagrams
|-- Dockerfile                    PoC container (single-stage, dev-friendly)
|-- Dockerfile.production         Production container (multi-stage, non-root, distroless)
|-- docker-compose.yml            PoC local stack
|-- docker-compose.production.yml Production local stack (Postgres + Redis + MinIO)
|-- requirements.txt              PoC dependencies (lean)
|-- requirements.production.txt   Production dependencies (full runtime stack)
|-- .env.production.example       Reference config for production env vars
|-- OUT_OF_SCOPE.md               11 production features deferred from the PoC
|-- PROPOSAL.md                   Hand-written job proposal
|-- SPEC.md                       Full specification
|-- README.md                     Project overview
|-- docs/production-vs-poc.md     What changed and why (this directory's companion doc)
```

## Deploying to production

### Prerequisites

- Azure subscription with: Container Apps, Postgres Flexible Server, Redis,
  Storage Account, Key Vault, Container Registry, Log Analytics, App Insights.
- Entra ID app registration for MS Graph (mailbox polling).
- User-assigned managed identity with AcrPull + Key Vault Secrets User.
- `kubectl`, `helm`, `az` CLI.

### 1. Provision Azure infrastructure

```bash
az deployment group create \
  --resource-group <rg> \
  --template-file deploy/azure-container-apps.bicep \
  --parameters \
    namePrefix=cpa \
    containerImage=cpaacr.azurecr.io/cpa-doc-intake:0.1.0 \
    uamiClientId=<UAMI-client-id> \
    uamiResourceId=<UAMI-resource-id> \
    tenantId=<tenant-id> \
    msGraphClientId=<ms-graph-app-id>
```

This creates:
- Container Apps environment
- Container App (the API)
- Postgres Flexible Server + `cpa_intake` database
- Azure Cache for Redis
- Storage Account with WORM-immutable `cpa-audit` container

### 2. Wire Key Vault to the cluster

Create the SecretProviderClass (operator-owned, not in this repo):

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: cpa-key-vault-secrets
  namespace: cpa-prod
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    userAssignedIdentityID: "<UAMI-client-id>"
    keyvaultName: "<vault-name>"
    objects: |
      - objectName: azure-openai-api-key
        objectType: secret
      - objectName: msgraph-client-secret
        objectType: secret
      - objectName: postgres-password
        objectType: secret
      - objectName: redis-password
        objectType: secret
  secretObjects:
    - secretName: cpa-intake-secrets
      type: Opaque
      data:
        - objectName: azure-openai-api-key
          key: azure-openai-api-key
        - objectName: msgraph-client-secret
          key: msgraph-client-secret
        - objectName: postgres-password
          key: postgres-password
        - objectName: redis-password
          key: redis-password
```

Then apply:

```bash
kubectl apply -f secret-provider-class.yaml
```

### 3. Deploy via Helm

```bash
helm upgrade --install cpa-intake helm/cpa-doc-intake/ \
  --namespace cpa-prod --create-namespace \
  --set image.tag=<image-sha> \
  --set azureOpenai.endpoint=https://cpa-openai.openai.azure.com/ \
  --set postgres.host=cpa-pg-prod.postgres.database.azure.com \
  --set redis.host=cpa-redis-prod.redis.cache.windows.net \
  --set msGraph.clientId=<ms-graph-app-id> \
  --set msGraph.tenantId=<tenant-id> \
  --set serviceAccount.annotations.azure\.workload\.identity/client-id=<UAMI-client-id>
```

### 4. Verify

```bash
helm test cpa-intake
# or, run the PoC smoke test against the ACA FQDN:
ACA_FQDN=$(az containerapp show -n cpa-api -g <rg> --query properties.configuration.ingress.fqdn -o tsv)
bash scripts/e2e_smoke.sh https://$ACA_FQDN
```

## Running the PoC locally

```bash
docker compose up -d                  # postgres + redis + minio + app
pytest                                # 20/20 tests
bash scripts/e2e_smoke.sh            # 6 synthetic documents, all queues + audit + idempotency
```

## Decision-driven phasing

Each production artifact maps to a specific PoC decision. See
`docs/production-vs-poc.md` for the cross-reference table.

| Decision | PoC artifact | Production artifact |
|---|---|---|
| 01-classifier-baseline | `src/classifier.py` | Containerized in `Dockerfile.production` |
| 02-router-confidence | `src/router.py` | helm `Deployment` + ACA autoscale 2→10 |
| 03-audit-immutability | `src/audit.py` | bicep WORM `cpa-audit` container |
| 04-intake-idempotency | `src/idempotency.py` | Postgres unique constraint + ingress size limit |
| 05-reviewer-workflow | `src/reviewer.py` | Entra ID OBO via `MS_GRAPH_CLIENT_ID` |