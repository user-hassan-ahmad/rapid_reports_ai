"""Pass 2 wording lab (spec 2026-10-09 §5.1): does Jev tell whether one report sentence says a brief label?

    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab build      # adds stored-case pairs (scratchpad)
    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab run --runs 2
    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab score --results <jsonl> [--min 0.8]

Gate: accuracy >= 95% at --min, and 0 trap pairs at or above --min. Production text stays under $RR_LAB_OUT/anchor_link/."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rapid_reports_ai import brief_anchor as ba
from rapid_reports_ai import report_reconcile as rc

from . import common

FIXTURE = Path(__file__).parent / "fixtures" / "anchor_link_pairs.json"
ARMS = {
    "S1": ba.LINK_WORDING,
    "S2": 'Read only this sentence. It states that "{t}" holds, for the same structure, side and level, in any wording.',
}


def pairs() -> list:
    out = common.read_json(FIXTURE)
    extra = common.lab_out("anchor_link") / "stored_pairs.json"
    return out + (common.read_json(extra) if extra.exists() else [])


def build() -> None:
    """Stored cases: pass 1 on each saved report; every label pass 1 left × each unit sharing a content word becomes a
    pair with gold null. Label gold by peer read in the JSON (true / false, trap where it applies)."""
    rows = common.metabase(
        "select id, candidate_reports->0->>'content' as report, candidate_reports->0->'brief'->'decisions' as d "
        "from reports where candidate_reports->0->'brief'->'decisions' is not null "
        "and created_at > now() - interval '30 days'")
    out = []
    for r in rows:
        d = r["d"] if isinstance(r["d"], dict) else json.loads(r["d"])   # Metabase may return jsonb as text
        if not isinstance(d, dict) or not r.get("report"):
            continue
        us = ba.units(r["report"])
        _, left = ba.match_terms(r["report"], ba.brief_labels(d), us)
        for lab in left:
            for u in us:
                if ba._words(lab.term) & ba._words(u.text):
                    out.append({"id": f"{str(r['id'])[:8]}:{lab.ref}:{u.start}", "label": lab.text, "sentence": u.text,
                                "gold": None})
    common.write_json(common.lab_out("anchor_link") / "stored_pairs.json", out)
    print(f"{len(out)} stored pairs; label gold before `run`")


async def _one(arm: str, p: dict) -> dict:
    q = {"type": "noul", "instructions": ARMS[arm].format(t=p["label"].rstrip(".")),
         "criteria": {"true": "the sentence says it", "false": "the sentence does not say it"}}
    ans = await rc._jev(p["sentence"], {"q": q})
    return {"id": p["id"], "arm": arm, "p": float(ans["q"]["noul"])}


async def run(runs: int) -> Path:
    common.load_env()
    todo = [p for p in pairs() if p.get("gold") is not None]
    out = common.out_file("anchor_link", "results", "jsonl")
    with open(out, "w") as f:
        for k in range(runs):
            for arm in ARMS:
                for p in todo:                    # one at a time: Jev only, cheap
                    f.write(json.dumps({**await _one(arm, p), "run": k}) + "\n")
    print(out)
    return out


def score(results: str, lo: float) -> None:
    gold = {p["id"]: p for p in pairs()}
    by: dict = {}
    for r in common.read_jsonl(results):
        by.setdefault(r["arm"], []).append(r)
    for arm, all_rs in by.items():
        for part, rs in (("all", all_rs), ("synthetic", [r for r in all_rs if ":" not in r["id"]]),
                         ("stored", [r for r in all_rs if ":" in r["id"]])):
            if not rs:
                continue
            ok = sum((r["p"] >= lo) == gold[r["id"]]["gold"] for r in rs)
            traps = [r["id"] for r in rs if gold[r["id"]].get("trap") and r["p"] >= lo]
            wrong = sorted({r["id"] for r in rs if (r["p"] >= lo) != gold[r["id"]]["gold"]})
            print(f"{arm} {part}: accuracy {ok}/{len(rs)} = {ok / len(rs):.1%}; trap links {len(traps)} "
                  f"{sorted(set(traps))}; wrong {wrong}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "score"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--results")
    ap.add_argument("--min", type=float, default=ba.LINK_MIN)
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        asyncio.run(run(a.runs))
    else:
        score(a.results, a.min)
