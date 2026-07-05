---
phase: 3
plan: intake-worker
type: standard
wave: 1
depends_on: [1, 2]
files_modified: [src/runner.py, scripts/demo.sh, scripts/clean.sh, samples/*.txt (copy)]
autonomous: true
requirements:
  - idempotent intake worker
  - SHA-256 of file content as idempotency key
  - re-running on processed files is a no-op
  - errors land in docs/dlq/, not crash the worker
  - supports both `once` and `watch` modes (CLI)
---

# Phase 03: Idempotent Intake Worker

**Goal:** Deliver `src/runner.py` — the file-watching worker that ties Phases 1+2 together. Reads docs from `docs/inbox/`, processes each end-to-end, writes `docs/extracted/<doc_id>.json` per doc, errors → `docs/dlq/`. This is Block C from `.planning/JOB-129-POC-SCOPE.md`.

**Context:** Pure local FS for the PoC. Production swaps to Celery worker pulling from Redis Streams (OUT_OF_SCOPE.md item 11).

## Tasks

### 1. runner.py module skeleton + idempotency helpers

**Wave:** 1
**Depends on:** —
**Files modified:** `src/runner.py`

<action>
Create `src/runner.py` with:

1. `from __future__ import annotations`
2. Imports: `hashlib, json, shutil, sys, time, pathlib (Path)` + module-local `from document_classifier import ...` and `from router import ...` (only after the `sys.path` boot guard below).
3. Boot guard at the top: `if __name__ == "__main__": sys.path.insert(0, str(Path(__file__).parent.parent))`.
4. Constants: `REPO_ROOT = Path(__file__).parent.parent`, `INBOX = REPO_ROOT / "docs" / "inbox"`, `EXTRACTED = REPO_ROOT / "docs" / "extracted"`, `DLQ = REPO_ROOT / "docs" / "dlq"`.
5. `_ensure_dirs()` — create INBOX, EXTRACTED, DLQ with parents=True, exist_ok=True.
6. `_hash_file(path) -> str` — SHA-256 of file bytes, return hex.
7. `_already_processed(content_hash) -> bool` — return True if `EXTRACTED / f"doc-{hash[:16]}.json"` exists.
8. `_read_text(path) -> str` — for PoC, read file as UTF-8 with `errors="replace"`. Production: Tesseract OCR.
</action>

<acceptance_criteria>
- File compiles
- `_hash_file` on a fixed-content file returns a stable 64-char hex string
- `_already_processed` is False for a fresh content_hash, True once the JSON file exists
- Constants resolve correctly when running `python -m src.runner` from worker root
</acceptance_criteria>

### 2. process_file() — the core end-to-end step

**Wave:** 1
**Depends on:** Task 1 + Phases 1+2
**Files modified:** `src/runner.py`

<read_first>
- src/document_classifier.py (extract_document API)
- src/router.py (route_document + append_audit_event)
</read_first>

<action>
Implement `process_file(path: Path) -> tuple[ExtractedDocument, RoutingDecision]`:

1. `content_hash = _hash_file(path)`, `doc_id = f"doc-{content_hash[:16]}"`.
2. `text = _read_text(path)`.
3. `extracted = extract_document(text, document_id=doc_id)`.
4. `decision = route_document(extracted)`.
5. Persist `EXTRACTED / f"{doc_id}.json"` with JSON containing `extracted.to_dict()`, `decision.to_dict()`, `source_file` (relative path), `source_size_bytes`.
6. `append_audit_event(doc_id=doc_id, event_type="extracted_and_routed", actor="intake-worker-poc", payload={...})` with the full routing summary.
7. Return `(extracted, decision)` for the caller.
</action>

<acceptance_criteria>
- Calling `process_file(p)` on an unsanitized path raises only if the file doesn't exist
- After process_file, `EXTRACTED/doc-<hash>.json` exists with the right shape
- After process_file, one new line is in `/tmp/poc-audit-log.jsonl`
- Idempotent: calling process_file twice on same path produces same doc_id (same content_hash)
</acceptance_criteria>

### 3. process_inbox_once() + watch_inbox() + argparse CLI

**Wave:** 1
**Depends on:** Task 2
**Files modified:** `src/runner.py`, `scripts/{demo,clean}.sh`

<action>
1. `process_inbox_once(verbose=True) -> dict`:
   - Call `_ensure_dirs()`.
   - Return summary dict: `{processed: [...], skipped: [...], errors: [...], decision_counts: {route: count}}`.
   - Iterate `INBOX.glob("*.txt")` sorted.
   - For each: hash, skip if `_already_processed`, else call `process_file` and append summary.
   - On exception: copy file to `DLQ`, append error to summary.
   - Print `[intake] summary: N processed, M skipped, K errors` at the end.

2. `watch_inbox(poll_seconds=2.0) -> None`:
   - `while True: process_inbox_once(verbose=False); time.sleep(poll_seconds)`.

3. `if __name__ == "__main__"` block:
   - `argparse` with subcommands `once` (one-shot) and `watch --interval 2.0` (loop).
   - Dispatch.

4. Create `scripts/clean.sh` that resets: `rm -rf docs/extracted/* docs/dlq/* /tmp/poc-audit-log.jsonl`.

5. Create `scripts/demo.sh`:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   cd "$(dirname "$0")/.."
   rm -rf docs/extracted/* docs/dlq/* /tmp/poc-audit-log.jsonl
   cp samples/*.txt docs/inbox/
   echo "==> Running intake (PoC runner)"
   PYTHONPATH=src python3 -m src.runner once
   echo
   echo "==> Idempotency check (re-run should skip everything)"
   PYTHONPATH=src python3 -m src.runner once
   ```
</action>

<acceptance_criteria>
- `bash scripts/demo.sh` from worker root: copies 5 samples into inbox, processes 5 → 5 extracted JSONs + 5 audit events; second run shows 5 skipped, 0 processed.
- `bash scripts/clean.sh` resets extracted/dlq/audit-log cleanly.
- `PYTHONPATH=src python -m src.runner once` works on a clean state.
- Watch mode is not tested in the PoC suite (sample-only); CLI exists for manual exploration.
</acceptance_criteria>

## Verification

```bash
bash scripts/clean.sh
bash scripts/demo.sh
# Expect: 5 processed → 5 extracted; 5 skipped on re-run; audit log has 5 events

PYTHONPATH=src pytest tests/ -q
# Expect: 18 passed (Phase 1 + 2 tests stay green; this phase has no new tests, only the demo end-to-end check)
```

## Out of scope for this phase

- Celery + Redis Streams bus — OUT_OF_SCOPE.md item 11
- Real MS Graph / SharePoint / S3 webhook intake — OUT_OF_SCOPE.md item 4
- Postgres-backed idempotency index — OUT_OF_SCOPE.md item 5
