#!/usr/bin/env python3
"""Build architecture.svg for the CPA Document Intake PoC.

Style C — Data Pipeline / ETL — appropriate for an event-driven document workflow.

Color scheme:
- #1E3A8A (deep blue) — system containers
- #F97316 (orange) — LLM/AI/decision stages
- #475569 (slate) — infrastructure
- #ffffff (white) — canvas background
"""
from pathlib import Path

OUT = Path(__file__).parent.parent / "diagrams" / "architecture.svg"
OUT.parent.mkdir(parents=True, exist_ok=True)

svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 720" width="1200" height="720">
  <rect width="1200" height="720" fill="#ffffff"/>

  <text x="40" y="40" font-family="Inter, system-ui, sans-serif" font-size="22" font-weight="700" fill="#0f172a">CPA Document Intake Pipeline — Architecture (PoC)</text>
  <text x="40" y="64" font-family="Inter, system-ui, sans-serif" font-size="13" fill="#475569">Event-driven ETL: email / SharePoint / portal docs to OCR + LLM to rule + LLM routing to staff review queues</text>

  <defs>
    <marker id="arrow" viewBox="0 -5 10 10" refX="9" refY="0" markerWidth="8" markerHeight="8" orient="auto">
      <path d="M0,-5 L10,0 L0,5 z" fill="#475569"/>
    </marker>
  </defs>

  <g font-family="Inter, system-ui, sans-serif" font-size="13" fill="#0f172a">
    <rect x="40" y="100" width="180" height="64" rx="8" ry="8" fill="#ffffff" stroke="#1E3A8A" stroke-width="2"/>
    <text x="130" y="128" text-anchor="middle" font-weight="600">Email</text>
    <text x="130" y="146" text-anchor="middle" fill="#475569">MS Graph webhook</text>

    <rect x="240" y="100" width="180" height="64" rx="8" ry="8" fill="#ffffff" stroke="#1E3A8A" stroke-width="2"/>
    <text x="330" y="128" text-anchor="middle" font-weight="600">SharePoint</text>
    <text x="330" y="146" text-anchor="middle" fill="#475569">Delta query</text>

    <rect x="440" y="100" width="180" height="64" rx="8" ry="8" fill="#ffffff" stroke="#1E3A8A" stroke-width="2"/>
    <text x="530" y="128" text-anchor="middle" font-weight="600">Firm Portal</text>
    <text x="530" y="146" text-anchor="middle" fill="#475569">S3 signed URL</text>
  </g>

  <rect x="280" y="200" width="240" height="60" rx="8" ry="8" fill="#1E3A8A" opacity="0.08" stroke="#1E3A8A" stroke-width="2"/>
  <text x="400" y="226" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="14" font-weight="600" fill="#0f172a">Message Bus</text>
  <text x="400" y="246" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="12" fill="#475569">Redis Streams (PoC) / RabbitMQ (prod)</text>

  <line x1="130" y1="164" x2="350" y2="200" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="330" y1="164" x2="400" y2="200" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="530" y1="164" x2="450" y2="200" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g font-family="Inter, system-ui, sans-serif" font-size="13" fill="#0f172a">
    <rect x="60" y="300" width="200" height="90" rx="8" ry="8" fill="#ffffff" stroke="#1E3A8A" stroke-width="2"/>
    <text x="160" y="328" text-anchor="middle" font-weight="700" fill="#1E3A8A">Intake Worker</text>
    <text x="160" y="346" text-anchor="middle" fill="#475569">Classify by form type</text>
    <text x="160" y="362" text-anchor="middle" fill="#475569">Store raw to MinIO</text>
    <text x="160" y="378" text-anchor="middle" fill="#475569">sha256 idempotency key</text>

    <rect x="320" y="300" width="200" height="90" rx="8" ry="8" fill="#ffffff" stroke="#F97316" stroke-width="2"/>
    <text x="420" y="328" text-anchor="middle" font-weight="700" fill="#F97316">Extractor Worker</text>
    <text x="420" y="346" text-anchor="middle" fill="#475569">Tesseract + PaddleOCR</text>
    <text x="420" y="362" text-anchor="middle" fill="#475569">Claude / GPT-4o JSON</text>
    <text x="420" y="378" text-anchor="middle" fill="#475569">Confidence per field</text>

    <rect x="580" y="300" width="200" height="90" rx="8" ry="8" fill="#ffffff" stroke="#F97316" stroke-width="2"/>
    <text x="680" y="328" text-anchor="middle" font-weight="700" fill="#F97316">Router Worker</text>
    <text x="680" y="346" text-anchor="middle" fill="#475569">Rule (YAML) + LLM exception</text>
    <text x="680" y="362" text-anchor="middle" fill="#475569">Idempotent by doc hash</text>
    <text x="680" y="378" text-anchor="middle" fill="#475569">Audit-events append-only</text>
  </g>

  <line x1="320" y1="260" x2="160" y2="300" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="400" y1="260" x2="420" y2="300" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="480" y1="260" x2="680" y2="300" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g font-family="Inter, system-ui, sans-serif" font-size="13" fill="#0f172a">
    <rect x="60" y="430" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#475569" stroke-width="2"/>
    <text x="160" y="458" text-anchor="middle" font-weight="600">MinIO (S3)</text>
    <text x="160" y="478" text-anchor="middle" fill="#475569">inbox / extracted / dlq/</text>
    <text x="160" y="496" text-anchor="middle" fill="#475569">field-AES-GCM encrypted</text>

    <rect x="320" y="430" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#475569" stroke-width="2"/>
    <text x="420" y="458" text-anchor="middle" font-weight="600">Postgres</text>
    <text x="420" y="478" text-anchor="middle" fill="#475569">jobs / events / audit</text>
    <text x="420" y="496" text-anchor="middle" fill="#475569">7-yr retention (IRC 6001)</text>

    <rect x="580" y="430" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#475569" stroke-width="2"/>
    <text x="680" y="458" text-anchor="middle" font-weight="600">Redis</text>
    <text x="680" y="478" text-anchor="middle" fill="#475569">durable streams</text>
    <text x="680" y="496" text-anchor="middle" fill="#475569">+ consumer groups</text>
  </g>

  <line x1="160" y1="390" x2="160" y2="430" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="420" y1="390" x2="420" y2="430" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="680" y1="390" x2="680" y2="430" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g font-family="Inter, system-ui, sans-serif" font-size="13" fill="#0f172a">
    <rect x="860" y="430" width="300" height="80" rx="8" ry="8" fill="#ffffff" stroke="#F97316" stroke-width="2"/>
    <text x="1010" y="458" text-anchor="middle" font-weight="700" fill="#F97316">Preparer Queue</text>
    <text x="1010" y="478" text-anchor="middle" fill="#475569">Routed by rule: W-2 / 1099-* / 1099-B</text>
    <text x="1010" y="496" text-anchor="middle" fill="#475569">Classified with conf >= 0.65</text>

    <rect x="860" y="520" width="300" height="80" rx="8" ry="8" fill="#ffffff" stroke="#F97316" stroke-width="2"/>
    <text x="1010" y="548" text-anchor="middle" font-weight="700" fill="#F97316">Senior Reviewer Queue</text>
    <text x="1010" y="568" text-anchor="middle" fill="#475569">Low conf OR K-1 / Engagement / Organizer</text>
    <text x="1010" y="586" text-anchor="middle" fill="#475569">Streamlit UI + email approval</text>

    <rect x="860" y="610" width="300" height="60" rx="8" ry="8" fill="#ffffff" stroke="#475569" stroke-width="2"/>
    <text x="1010" y="636" text-anchor="middle" font-weight="600">Dead-Letter Queue</text>
    <text x="1010" y="654" text-anchor="middle" fill="#475569">Schema-invalid docs / irrecoverable</text>
  </g>

  <line x1="780" y1="345" x2="860" y2="470" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="780" y1="345" x2="860" y2="560" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>
  <line x1="780" y1="345" x2="860" y2="640" stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g font-family="Inter, system-ui, sans-serif" font-size="12" fill="#475569">
    <rect x="40" y="610" width="780" height="80" rx="8" ry="8" fill="#ffffff" stroke="#475569" stroke-width="1"/>
    <text x="60" y="634" font-weight="700" fill="#0f172a">PoC scope</text>
    <text x="60" y="654">text-only classifier + extractor (PoC; production swaps in Tesseract + Azure OpenAI)</text>
    <text x="60" y="670">in-memory idempotency by SHA-256 of file content; DB-backed key in production</text>
    <text x="60" y="686">file-based audit log (PoC); production swaps in Postgres append-only with 7-yr retention</text>
  </g>
</svg>
"""

OUT.write_text(svg)
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
