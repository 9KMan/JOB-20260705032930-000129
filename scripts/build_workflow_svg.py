#!/usr/bin/env python3
"""Build workflow.svg for the CPA Document Intake PoC.

Style B — clean 2D flowchart for the end-to-end document lifecycle.

Color scheme (slate + blue):
- #334155 (slate-700) — system containers, headers
- #2563EB (blue-600) — happy-path stages
- #DC2626 (red-600) — error/demotion steps
- #ffffff (white) — canvas background
"""
from pathlib import Path

OUT = Path(__file__).parent.parent / "diagrams" / "workflow.svg"
OUT.parent.mkdir(parents=True, exist_ok=True)

svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 540" width="1200" height="540">
  <rect width="1200" height="540" fill="#ffffff"/>

  <text x="40" y="40" font-family="Inter, system-ui, sans-serif" font-size="22" font-weight="700" fill="#0f172a">CPA Document Intake — Workflow</text>
  <text x="40" y="64" font-family="Inter, system-ui, sans-serif" font-size="13" fill="#475569">Lifecycle of a single document from intake to preparer/reviewer queue</text>

  <defs>
    <marker id="arrow" viewBox="0 -5 10 10" refX="9" refY="0" markerWidth="8" markerHeight="8" orient="auto">
      <path d="M0,-5 L10,0 L0,5 z" fill="#334155"/>
    </marker>
    <marker id="arrow-red" viewBox="0 -5 10 10" refX="9" refY="0" markerWidth="8" markerHeight="8" orient="auto">
      <path d="M0,-5 L10,0 L0,5 z" fill="#DC2626"/>
    </marker>
  </defs>

  <g font-family="Inter, system-ui, sans-serif" font-size="13" fill="#0f172a">
    <!-- Stage 1: Intake -->
    <rect x="40" y="110" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#2563EB" stroke-width="2"/>
    <text x="140" y="138" text-anchor="middle" font-weight="700" fill="#2563EB">1. Source receives doc</text>
    <text x="140" y="158" text-anchor="middle" fill="#475569">email / SharePoint / portal</text>
    <text x="140" y="174" text-anchor="middle" fill="#475569">dedupe by SHA-256</text>

    <!-- Stage 2: Classify -->
    <rect x="290" y="110" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#2563EB" stroke-width="2"/>
    <text x="390" y="138" text-anchor="middle" font-weight="700" fill="#2563EB">2. Classify form type</text>
    <text x="390" y="158" text-anchor="middle" fill="#475569">W-2 / 1099-* / K-1 / Unknown</text>
    <text x="390" y="174" text-anchor="middle" fill="#475569">confidence 0.0 to 0.95</text>

    <!-- Stage 3: Extract -->
    <rect x="540" y="110" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#2563EB" stroke-width="2"/>
    <text x="640" y="138" text-anchor="middle" font-weight="700" fill="#2563EB">3. Extract fields</text>
    <text x="640" y="158" text-anchor="middle" fill="#475569">OCR + LLM JSON schema</text>
    <text x="640" y="174" text-anchor="middle" fill="#475569">field-level confidence</text>

    <!-- Stage 4: Decision -->
    <polygon points="990,110 1110,150 990,190 870,150" fill="#ffffff" stroke="#334155" stroke-width="2"/>
    <text x="990" y="146" text-anchor="middle" font-weight="700" fill="#334155">4. Route decision</text>
    <text x="990" y="162" text-anchor="middle" fill="#475569">rule + confidence</text>

    <!-- Stage 5: Outcomes -->
    <rect x="40" y="300" width="240" height="80" rx="8" ry="8" fill="#ffffff" stroke="#2563EB" stroke-width="2"/>
    <text x="160" y="328" text-anchor="middle" font-weight="700" fill="#2563EB">5a. Preparer queue</text>
    <text x="160" y="350" text-anchor="middle" fill="#475569">high-confidence, known type</text>
    <text x="160" y="366" text-anchor="middle" fill="#475569">staff reviews in Streamlit</text>

    <rect x="320" y="300" width="240" height="80" rx="8" ry="8" fill="#ffffff" stroke="#F97316" stroke-width="2"/>
    <text x="440" y="328" text-anchor="middle" font-weight="700" fill="#F97316">5b. Senior reviewer</text>
    <text x="440" y="350" text-anchor="middle" fill="#475569">low conf / K-1 / Unknown</text>
    <text x="440" y="366" text-anchor="middle" fill="#475569">override + reason captured</text>

    <rect x="600" y="300" width="200" height="80" rx="8" ry="8" fill="#ffffff" stroke="#DC2626" stroke-width="2"/>
    <text x="700" y="328" text-anchor="middle" font-weight="700" fill="#DC2626">5c. DLQ</text>
    <text x="700" y="350" text-anchor="middle" fill="#475569">schema invalid</text>
    <text x="700" y="366" text-anchor="middle" fill="#475569">manual escalation only</text>

    <!-- Stage 6: Audit + Completion -->
    <rect x="840" y="300" width="320" height="80" rx="8" ry="8" fill="#ffffff" stroke="#334155" stroke-width="2"/>
    <text x="1000" y="328" text-anchor="middle" font-weight="700" fill="#334155">6. Audit + retention</text>
    <text x="1000" y="350" text-anchor="middle" fill="#475569">append-only audit_event</text>
    <text x="1000" y="366" text-anchor="middle" fill="#475569">7-yr retention (IRC 6001)</text>

    <!-- Arrows between top stages -->
    <line x1="240" y1="150" x2="290" y2="150" stroke="#334155" stroke-width="1.5" marker-end="url(#arrow)"/>
    <line x1="490" y1="150" x2="540" y2="150" stroke="#334155" stroke-width="1.5" marker-end="url(#arrow)"/>
    <line x1="740" y1="150" x2="870" y2="150" stroke="#334155" stroke-width="1.5" marker-end="url(#arrow)"/>

    <!-- Decision branching -->
    <line x1="990" y1="190" x2="160" y2="300" stroke="#2563EB" stroke-width="1.5" marker-end="url(#arrow)"/>
    <text x="540" y="225" font-size="11" fill="#2563EB">conf >= 0.65</text>
    <line x1="990" y1="190" x2="440" y2="300" stroke="#F97316" stroke-width="1.5" marker-end="url(#arrow)"/>
    <text x="600" y="270" font-size="11" fill="#F97316">conf &lt; 0.65</text>
    <line x1="990" y1="190" x2="700" y2="300" stroke="#DC2626" stroke-width="1.5" marker-end="url(#arrow)"/>
    <text x="780" y="270" font-size="11" fill="#DC2626">schema invalid</text>
    <line x1="990" y1="190" x2="1000" y2="300" stroke="#334155" stroke-width="1.5" marker-end="url(#arrow)"/>
    <text x="1050" y="240" font-size="11" fill="#334155">all paths</text>

    <!-- Outcomes to Audit -->
    <line x1="160" y1="380" x2="900" y2="380" stroke="#334155" stroke-width="1.5" stroke-dasharray="4 2"/>
    <line x1="440" y1="380" x2="920" y2="380" stroke="#334155" stroke-width="1.5" stroke-dasharray="4 2"/>
    <line x1="700" y1="380" x2="940" y2="380" stroke="#334155" stroke-width="1.5" stroke-dasharray="4 2"/>
    <line x1="980" y1="380" x2="1000" y2="380" stroke="#334155" stroke-width="1.5" marker-end="url(#arrow)"/>
    <text x="970" y="405" font-size="11" fill="#334155">every routing decision emits one audit event</text>
  </g>

  <!-- Footer: idempotency note -->
  <g font-family="Inter, system-ui, sans-serif" font-size="12" fill="#475569">
    <rect x="40" y="430" width="1120" height="80" rx="8" ry="8" fill="#ffffff" stroke="#475569" stroke-width="1"/>
    <text x="60" y="456" font-weight="700" fill="#0f172a">Idempotency</text>
    <text x="60" y="476">Every document is keyed by SHA-256 of file content. Re-processing the same doc returns the same doc_id and routing decision.</text>
    <text x="60" y="492">Duplicate webhook delivery (the most common production race) cannot double-route a document.</text>
  </g>
</svg>
"""

OUT.write_text(svg)
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
