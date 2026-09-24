"""Summarise a dump of production logs containing canvas.triage.shadow lines.

Usage:
    railway logs ... > /tmp/shadow.log
    .venv/bin/python -m rapid_reports_ai.scripts.triage_shadow_report /tmp/shadow.log

Labels come from the derived action, so 'expected_action' here is the derived
label and accuracy means agreement (lenient by construction; see AGREEMENT_MAP).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rapid_reports_ai.scripts.triage_summary import Record, format_summary, summarise

MARK = "[canvas.triage.shadow] "


def parse_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        i = line.find(MARK)
        if i == -1:
            continue
        try:
            out.append(json.loads(line[i + len(MARK):]))
        except json.JSONDecodeError:
            continue
    return out


def to_records(events: list[dict]) -> list[Record]:
    records: list[Record] = []
    for n, ev in enumerate(events):
        for cand in ("jev", "qwen"):
            slot = ev.get(cand) or {}
            # 'agrees' already encodes the lenient map; represent agreement as a match.
            expected = slot.get("action") if slot.get("agrees") else f"derived:{ev.get('derived')}"
            records.append(Record(
                id=f"{n}-{ev.get('utterance_sha8')}", candidate=cand, expected_action=expected or "",
                action=slot.get("action"), confidence=slot.get("confidence"),
                latency_ms=slot.get("latency_ms") or 0, cost_usd=slot.get("cost_usd"), hard=False,
                error=slot.get("error"), is_correction=None, expected_is_correction=None,
                needs_committed_edit=None, expected_needs_committed_edit=None,
            ))
    return records


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: triage_shadow_report <logfile>", file=sys.stderr)
        return 2
    events = parse_lines(Path(argv[1]).read_text())
    print(f"{len(events)} shadow events")
    print(format_summary(summarise(to_records(events))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
