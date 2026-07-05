---
phase: 4
decision: "Can the intake worker process a directory of docs end-to-end WITHOUT double-processing on retry?"
plan: intake-worker-idempotency
type: standard
wave: 1
depends_on: [1, 2, 3]
files_modified: [src/runner.py, scripts/clean.sh, scripts/demo.sh]
autonomous: true
acceptance_decision: "PASS if first run processes 5 docs (5 extracted JSONs + 5 audit events), second run shows 5 skipped + 0 processed (idempotent), and an exception in process_file doesn't crash the worker (file gets moved to docs/dlq/)."
---

# Phase 04 — Intake Idempotency

## Question this phase answers

> "If the worker is interrupted mid-run (worker crash, duplicate webhook delivery, manual re-invocation), will double-processing happen, or will the system stay idempotent?"

## Decision outcome

| Approach | Pass | Fail |
|---|---|---|
| SHA-256 of file content + filesystem existence check for `docs/extracted/<hash>.json` | First run: 5 processed. Second run: 5 skipped. No double-routing. | Worker crashes the loop on a single bad file; second run duplicates 5 events. |

If **pass**: We can hand the worker to a CPA firm and trust it won't double-route a document when their webhook fires twice.
If **fail**: Production needs a database-backed idempotency index (Postgres `documents` keyed by hash).

## Files to Create

src/runner.py
scripts/clean.sh
scripts/demo.sh

## Tasks

### Task 01 — Idempotent worker with CLI subcommands

```file:src/runner.py
"""Idempotent intake worker. Re-run is a no-op."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from document_classifier import DocType, ExtractedDocument, classify, extract_document
from router import Route, RoutingDecision, append_audit_event, route_document

REPO_ROOT = Path(__file__).parent.parent
INBOX = REPO_ROOT / "docs" / "inbox"
EXTRACTED = REPO_ROOT / "docs" / "extracted"
DLQ = REPO_ROOT / "docs" / "dlq"


def _ensure_dirs() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    DLQ.mkdir(parents=True, exist_ok=True)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _already_processed(content_hash: str) -> bool:
    return (EXTRACTED / f"doc-{content_hash[:16]}.json").exists()


def _read_text(path: Path) -> str:
    """PoC: text input only. Production: Tesseract OCR."""
    return path.read_text(encoding="utf-8", errors="replace")


def process_file(path: Path) -> tuple[ExtractedDocument, RoutingDecision]:
    content_hash = _hash_file(path)
    doc_id = f"doc-{content_hash[:16]}"
    text = _read_text(path)
    extracted = extract_document(text, document_id=doc_id)
    decision = route_document(extracted)
    with (EXTRACTED / f"{doc_id}.json").open("w") as f:
        json.dump({
            "extracted": extracted.to_dict(),
            "routing": decision.to_dict(),
            "source_file": str(path.relative_to(REPO_ROOT)),
            "source_size_bytes": path.stat().st_size,
        }, f, indent=2)
    append_audit_event(
        doc_id=doc_id, event_type="extracted_and_routed",
        actor="intake-worker-poc",
        payload={
            "doc_type": extracted.doc_type.value,
            "route": decision.route.value,
            "classification_confidence": extracted.classification_confidence,
            "avg_field_confidence": decision.avg_field_confidence,
            "flagged_fields": decision.flagged_fields,
        },
    )
    return extracted, decision


def process_inbox_once(verbose: bool = True) -> dict:
    _ensure_dirs()
    summary = {"processed": [], "skipped": [], "errors": [], "decision_counts": {}}
    files = sorted(INBOX.glob("*.txt"))
    if verbose:
        print(f"[intake] scanning {INBOX} - {len(files)} files")
    for path in files:
        try:
            content_hash = _hash_file(path)
            doc_id = f"doc-{content_hash[:16]}"
            if _already_processed(content_hash):
                summary["skipped"].append({"file": str(path), "doc_id": doc_id, "reason": "already_processed"})
                if verbose:
                    print(f"  [skip]  {path.name} (already processed -> {doc_id})")
                continue
            extracted, decision = process_file(path)
            summary["processed"].append({
                "file": str(path), "doc_id": extracted.document_id,
                "doc_type": extracted.doc_type.value, "route": decision.route.value,
                "class_confidence": extracted.classification_confidence,
                "flagged_fields": decision.flagged_fields,
            })
            summary["decision_counts"][decision.route.value] = (
                summary["decision_counts"].get(decision.route.value, 0) + 1
            )
            if verbose:
                flag_str = f"  warn {len(decision.flagged_fields)} flagged" if decision.flagged_fields else ""
                print(f"  [done]  {path.name:35s} -> {extracted.doc_type.value:14s} -> {decision.route.value:18s} (cls={extracted.classification_confidence:.2f}{flag_str})")
        except Exception as exc:
            summary["errors"].append({"file": str(path), "error": str(exc)})
            try:
                shutil.copy2(path, DLQ / path.name)
            except Exception:
                pass
            if verbose:
                print(f"  [ERROR] {path.name}: {exc}")
    if verbose:
        print(f"\n[intake] summary: {len(summary['processed'])} processed, {len(summary['skipped'])} skipped, {len(summary['errors'])} errors")
        if summary["decision_counts"]:
            print(f"[intake] routes: {summary['decision_counts']}")
    return summary


def watch_inbox(poll_seconds: float = 2.0) -> None:
    print(f"[intake] watching {INBOX} every {poll_seconds}s - Ctrl-C to stop")
    while True:
        process_inbox_once(verbose=False)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CPA doc-intake PoC runner")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("once", help="process inbox once and exit")
    p_watch = sub.add_parser("watch", help="loop and process as files appear")
    p_watch.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    if args.cmd == "watch":
        watch_inbox(poll_seconds=args.interval)
    else:
        process_inbox_once()
```

### Task 02 — Demo + clean scripts

```file:scripts/demo.sh
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
echo
echo "Audit events: $(wc -l < /tmp/poc-audit-log.jsonl)"
```

```file:scripts/clean.sh
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf docs/extracted/* docs/dlq/* /tmp/poc-audit-log.jsonl
echo "Cleaned."
```

## Done When

1. `python -m py_compile src/runner.py` succeeds.
2. `bash scripts/clean.sh` clears extracted/dlq/audit-log.
3. `bash scripts/demo.sh` processes 5 samples on run 1, then **skips all 5 on run 2** (idempotency).
4. `/tmp/poc-audit-log.jsonl` has exactly 5 lines after run 1 (5 events for 5 docs).
5. Worker doesn't crash on a malformed file — instead copies it to `docs/dlq/`.
