#!/usr/bin/env python3
"""
validate_gsd_plans.py — For each .planning/phases/N-name/PLAN-01.md,
parse the frontmatter + content, validate the listed files against the
actual repo state, and report what gsd-execute-plan.py WOULD have done.

This is a "planning-vs-execution alignment check" — proves that the
shipped code matches what the plans say should exist, without needing to
re-run the OpenCode orchestrator (which would churn the git history).

Usage:
    python3 scripts/validate_gsd_plans.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PHASES_DIR = REPO_ROOT / ".planning" / "phases"


def parse_plan(plan_path: Path) -> dict:
    """Extract YAML frontmatter + acceptance criteria from a PLAN-01.md."""
    text = plan_path.read_text()
    meta = {}

    # Frontmatter
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        current_key = None
        for line in fm_match.group(1).splitlines():
            m = re.match(r"^(\w+):\s*(.+?)\s*$", line)
            m_list = re.match(r"^(\w+):\s*$", line)  # empty-list key like `requirements:`
            if m:
                key, val = m.group(1), m.group(2)
                current_key = key
                if val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if inner:
                        meta[key] = [s.strip() for s in inner.split(",")]
                    else:
                        meta[key] = []
                elif val in ("true", "false"):
                    meta[key] = val == "true"
                else:
                    meta[key] = val
            elif m_list:
                current_key = m_list.group(1)
                meta.setdefault(current_key, [])
            elif line.startswith("  - ") and current_key:
                item = line.strip().lstrip("-").strip()
                if isinstance(meta.get(current_key), list):
                    meta[current_key].append(item)

    # Wave value: reading frontmatter wave as int
    if isinstance(meta.get("wave"), str) and meta["wave"].isdigit():
        meta["wave"] = int(meta["wave"])
    if isinstance(meta.get("phase"), str) and meta["phase"].isdigit():
        meta["phase"] = int(meta["phase"])

    # depends_on may also be a list
    depends_on = meta.get("depends_on", [])
    if isinstance(depends_on, str):
        meta["depends_on"] = [s.strip() for s in depends_on.split(",") if s.strip()]  # noqa

    # Files mentioned in body (more authoritative than frontmatter)
    body_files = re.findall(r"\*\*Files modified:\*\*\s*(.+?)$", text, re.MULTILINE)
    for bf in body_files:
        # bf is the line content, e.g. "src/foo.py, tests/test_foo.py"
        f = bf.strip()
        if f and f != "":
            for path in re.split(r",\s+", f):
                if path and path not in meta.get("files_modified", []):
                    meta.setdefault("files_modified", []).append(path)

    # Acceptance criteria count
    meta["acceptance_criteria_count"] = len(re.findall(r"<acceptance_criteria>", text))

    return meta


def check_files_exist(file_list: list[str]) -> tuple[list[str], list[str]]:
    """Return (present, missing) for each path in file_list."""
    present = []
    missing = []
    for f in file_list:
        # Strip backticks + parenthetical notes (e.g., "scripts/{demo,clean}.sh" or "x.py (copy)")
        clean = f.strip().strip("`")
        clean = re.sub(r"\s*\(.*?\)\s*$", "", clean).strip()
        # Expand brace alternatives: "scripts/{demo,clean}.sh" -> check each
        if "{" in clean and "}" in clean:
            stem, rest = clean.split("}", 1) if "}" in clean else (clean, "")
            prefix = stem[: stem.find("{")]
            inside = stem[stem.find("{") + 1 :]
            alternatives = inside.split(",")
            brace_ok = False
            for alt in alternatives:
                expanded = prefix + alt.strip() + rest
                if (REPO_ROOT / expanded).exists():
                    brace_ok = True
                    break
            if brace_ok:
                present.append(f)
            else:
                missing.append(f)
        elif "*" in clean:
            matches = list(REPO_ROOT.glob(clean))
            (present if matches else missing).append(f)
        else:
            p = REPO_ROOT / clean
            (present if p.exists() else missing).append(f)
    return present, missing


def main() -> int:
    if not PHASES_DIR.exists():
        print(f"ERROR: {PHASES_DIR} not found")
        return 1

    phases = sorted(PHASES_DIR.iterdir())
    if not phases:
        print(f"ERROR: no phases found in {PHASES_DIR}")
        return 1

    print(f"Validating {len(phases)} GSD plans against repo state")
    print(f"  Repo root: {REPO_ROOT}")
    print(f"  Phases:    {PHASES_DIR}\n")

    total_files = 0
    total_present = 0
    total_missing = 0
    all_ok = True

    for phase_dir in phases:
        plan_path = phase_dir / "PLAN-01.md"
        if not plan_path.exists():
            print(f"  ⚠ {phase_dir.name} — no PLAN-01.md found")
            all_ok = False
            continue

        meta = parse_plan(plan_path)
        phase_num = meta.get("phase", "?")
        phase_name = meta.get("plan", phase_dir.name)
        files = meta.get("files_modified", [])
        depends_on = meta.get("depends_on", [])

        present, missing = check_files_exist(files)

        total_files += len(files)
        total_present += len(present)
        total_missing += len(missing)

        status = "OK" if not missing else "FAIL"
        print(f"  [{status}] Phase {phase_num}: {phase_name}")
        print(f"          depends_on: {depends_on or '[]'}")
        print(f"          wave:       {meta.get('wave', '?')}")
        print(f"          autonomous: {meta.get('autonomous', '?')}")
        print(f"          files:      {len(present)}/{len(files)} present")
        print(f"          acceptance: {meta.get('acceptance_criteria_count', 0)} criteria")
        if missing:
            print(f"          MISSING:    {missing}")
            all_ok = False
        print()

    print(f"Summary: {total_present}/{total_files} files present, {total_missing} missing")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
