"""Idempotent intake worker.

Reads documents from `docs/inbox/`, classifies + extracts, routes, and
writes the structured result to `docs/extracted/<doc_id>.json`.

Idempotency:
- Documents are keyed by SHA-256 hash of their content
- Running the worker twice on the same file produces the same routing
- Already-processed docs are logged and skipped

In production this would be a Celery worker pulling from Redis Streams.
For the PoC it's a plain script — `python -m src.runner`.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from document_classifier import (
    DocType,
    ExtractedDocument,
    classify,
    extract_document,
)
from router import (
    Route,
    RoutingDecision,
    append_audit_event,
    route_document,
)

REPO_ROOT = Path(__file__).parent.parent
INBOX = REPO_ROOT / "docs" / "inbox"
EXTRACTED = REPO_ROOT / "docs" / "extracted"
DLQ = REPO_ROOT / "docs" / "dlq"


def _ensure_dirs() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    DLQ.mkdir(parents=True, exist_ok=True)


def _hash_file(path: Path) -> str:
    """SHA-256 hash of file contents — used as idempotency key."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _already_processed(content_hash: str) -> bool:
    """True if we've already extracted a doc with this content hash."""
    target = EXTRACTED / f"doc-{content_hash[:16]}.json"
    return target.exists()


def _read_text(path: Path) -> str:
    """PoC: assume text input. In prod, PDF → Tesseract OCR or pdftotext."""
    if path.suffix.lower() in {".txt", ".md", ".csv"}:
        return path.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def process_file(path: Path) -> tuple[ExtractedDocument, RoutingDecision]:
    """Process one file end-to-end. Returns (extracted, routing_decision)."""
    content_hash = _hash_file(path)
    doc_id = f"doc-{content_hash[:16]}"

    text = _read_text(path)
    extracted = extract_document(text, document_id=doc_id)
    decision = route_document(extracted)

    target = EXTRACTED / f"{doc_id}.json"
    with target.open("w") as f:
        json.dump(
            {
                "extracted": extracted.to_dict(),
                "routing": decision.to_dict(),
                "source_file": str(path.relative_to(REPO_ROOT)),
                "source_size_bytes": path.stat().st_size,
            },
            f,
            indent=2,
        )

    append_audit_event(
        doc_id=doc_id,
        event_type="extracted_and_routed",
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
    """
    Process every .txt file in INBOX once. Skips already-processed files.
    Returns a summary: {processed, skipped, errors}.
    """
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
                "file": str(path),
                "doc_id": extracted.document_id,
                "doc_type": extracted.doc_type.value,
                "route": decision.route.value,
                "class_confidence": extracted.classification_confidence,
                "flagged_fields": decision.flagged_fields,
            })
            summary["decision_counts"][decision.route.value] = (
                summary["decision_counts"].get(decision.route.value, 0) + 1
            )

            if verbose:
                flag_str = f"  warn {len(decision.flagged_fields)} flagged" if decision.flagged_fields else ""
                print(f"  [done]  {path.name:35s} -> {extracted.doc_type.value:14s} -> {decision.route.value:18s} "
                      f"(cls={extracted.classification_confidence:.2f}{flag_str})")
        except Exception as exc:
            summary["errors"].append({"file": str(path), "error": str(exc)})
            try:
                shutil.copy2(path, DLQ / path.name)
            except Exception:
                pass
            if verbose:
                print(f"  [ERROR] {path.name}: {exc}")

    if verbose:
        print(f"\n[intake] summary: {len(summary['processed'])} processed, "
              f"{len(summary['skipped'])} skipped, {len(summary['errors'])} errors")
        if summary["decision_counts"]:
            print(f"[intake] routes: {summary['decision_counts']}")

    return summary


def watch_inbox(poll_seconds: float = 2.0) -> None:
    print(f"[intake] watching {INBOX} every {poll_seconds}s - Ctrl-C to stop")
    while True:
        process_inbox_once(verbose=False)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CPA doc-intake PoC runner")
    sub = parser.add_subparsers(dest="cmd")

    p_once = sub.add_parser("once", help="process inbox once and exit")
    p_watch = sub.add_parser("watch", help="loop and process as files appear")
    p_watch.add_argument("--interval", type=float, default=2.0)

    args = parser.parse_args()
    if args.cmd == "watch":
        watch_inbox(poll_seconds=args.interval)
    else:
        process_inbox_once()
