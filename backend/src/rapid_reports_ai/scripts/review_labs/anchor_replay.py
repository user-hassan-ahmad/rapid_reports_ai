"""Code-only stage (spec 2026-10-09 §5.2): brief_anchor on every stored report with brief decisions, no regeneration.
Pass 2 runs live (Jev, cheap); the contradiction scores are not re-asked, so the rules use the stored flags only
(no stored sentence types, so `would_remove` is empty by construction here; the stored anchor_log, when the report
has one, is printed beside it).

    RR_LAB_OUT=<scratchpad> python -m rapid_reports_ai.scripts.review_labs.anchor_replay [--days 30]

Writes $RR_LAB_OUT/anchor_replay/<id8>.json per case and prints, per report: one table row per label (ref, action,
source, how, span_text, shadowed_by, whether the review engine's brief_normals.owned() owns it), then the stored
quality_check's kept_dictated_negative entries and contradiction flags (the real-data zone for brief removals)."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from rapid_reports_ai import brief_anchor as ba
from rapid_reports_ai.report_review import is_negative
from rapid_reports_ai.review_engine.brief_normals import owned

from . import common

SQL = """select id::text as id, candidate_reports->0->>'content' as report,
  candidate_reports->0->'brief'->'decisions' as d, candidate_reports->0->'quality_check' as qc
from reports where candidate_reports->0->'brief'->'decisions' is not null
  and created_at > now() - interval '{days} days' order by created_at"""


def _obj(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


async def main(days: int) -> None:
    common.load_env()
    out = common.lab_out("anchor_replay")
    for r in common.metabase(SQL.format(days=int(days))):
        d, qc, report = _obj(r["d"]), _obj(r["qc"]), r.get("report") or ""
        if not isinstance(d, dict) or not report:
            continue
        anchors = await ba.anchor(report, d)
        flags = qc.get("flags") or []
        contra = [f for f in flags if f.get("kind") == "contradiction"]
        rules = ba.brief_rules(report, anchors, {f["text"]: float(f.get("score") or 0) for f in contra},
                               flagged=[f["text"] for f in contra if is_negative(f["text"])],
                               review_contra=[f["text"] for f in contra if not is_negative(f["text"])])
        log = ba.anchor_log(anchors, rules)
        id8 = r["id"][:8]
        common.write_json(out / f"{id8}.json", {"id": r["id"], "anchors": [asdict(a) for a in anchors], "log": log,
                                                "rules": rules, "stored_anchor_log": qc.get("anchor_log"),
                                                "kept_dictated_negative": qc.get("kept_dictated_negative") or [],
                                                "contradiction_flags": contra})
        print(f"\n== {id8}  labels {log['labels']}  term+jev {log['by_term_jev']}  jev {log['by_jev']}  "
              f"unanchored {len(log['unanchored'])}  shadowed {len(log['shadowed'])}  "
              f"brief_errors {[e['ref'] for e in log['brief_errors']]}")
        for a in anchors:
            print(f"  {a.ref:16} {a.action:12} {a.source[:22]:22} {a.how:5} owned={'Y' if owned(asdict(a)) else 'n'} "
                  f"{a.span_text[:70]!r} {('<- ' + a.shadowed_by) if a.shadowed_by else ''}")
        for k in qc.get("kept_dictated_negative") or []:
            print(f"  KEPT_DICTATED c={k.get('contradiction')} d={k.get('dictated')} {k.get('text', '')[:90]!r}")
        for f in contra:
            print(f"  CONTRA {f.get('score'):.3f} neg={is_negative(f['text'])} {f['text'][:90]!r}")
        if rules["conflicts"] or rules["protect"]:
            print(f"  RULES protect {len(rules['protect'])} conflicts "
                  f"{[(c['reason'], c['refs']) for c in rules['conflicts']]}")
        stored = qc.get("anchor_log")
        if stored:
            print(f"  STORED anchor_log: would_remove {stored.get('would_remove_by_brief')} "
                  f"brief_errors {stored.get('brief_errors')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    asyncio.run(main(ap.parse_args().days))
