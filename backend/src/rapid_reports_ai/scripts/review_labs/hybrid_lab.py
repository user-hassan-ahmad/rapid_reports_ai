"""Hybrid certainty rule validation on real wording (2026-10-04, after type_tier_lab).

Rule: overstated when rank(report tier from code `checks.hedge_tag`) > rank(Jev D2 dictation tier), OR both are fact
and C1n ≥ 0.5 (a meaning upgrade with no hedge word). Sets:
  a. certainty_lab's faithful items (label same; bar 0–1 false alarms)
  b. certainty_lab's real upgrades (= the gate_b_gold certainty_upgrade items) and its hardened synthetic ones
  c. real report clauses of the 40 e2e runs vs their dictation, peer-labelled blind (same / upgrade / not_dictated)
  d. real dictated statements re-hedged with real-world hedges ("suspicious for", "worrisome for", "concerning for",
     "appears to represent", "raises the possibility of", "query", "cannot be excluded"), labelled by construction.
Arms in one dictation-state request per item: D2 (4 tiers), D2n (4 tiers + not_stated), C1n.

    RR_LAB_OUT=<scratchpad>/review_labs python -m rapid_reports_ai.scripts.review_labs.hybrid_lab build
    ... hybrid_lab run [--limit 2]
    ... hybrid_lab score --results <jsonl> [--results2 <jsonl>]"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from typing import Dict, List, Optional

from rapid_reports_ai.review_engine.checks import hedge_tag

from . import common
from .certainty_lab import question as certainty_question
from .type_tier_lab import (D2, GATE, RANK, TIER_CRITERIA, _cases, _review_eval, _support_state, choice_of,
                            tier_question)

CODE_TIER = {"definite": "fact", "probable": "probable", "possible": "possible", "negated": "excluded"}
D2N_CRITERIA = {**TIER_CRITERIA, "not_stated": "not stated: the dictated findings do not mention this finding"}


def report_tier(clause: str) -> str:
    return CODE_TIER[hedge_tag(clause)]


def flag(rt: str, dt: Optional[str], c1n: Optional[float]) -> Optional[bool]:
    """The hybrid rule. None when the dictation tier is unknown (no answer, or not_stated: W1n's territory)."""
    if dt not in RANK:
        return None
    return RANK[rt] > RANK[dt] or (rt == dt == "fact" and c1n is not None and c1n >= 0.5)


REAL_HEDGES = {
    "suspicious for": ("probable", "{O}, suspicious for {F}.", "Appearances are suspicious for {F}."),
    "worrisome for": ("probable", "{O}, worrisome for {F}.", "Appearances are worrisome for {F}."),
    "concerning for": ("probable", "{O}, concerning for {F}.", "Appearances are concerning for {F}."),
    "appears to represent": ("probable", "{O}, which appears to represent {F}.", "This appears to represent {F}."),
    "raises the possibility of": ("possible", "{O}, raising the possibility of {F}.",
                                  "Appearances raise the possibility of {F}."),
    "query": ("possible", "{O}, query {F}.", "Query {F}."),
    "cannot be excluded": ("possible", "{O}; {F} cannot be excluded.", "{Fc} cannot be excluded."),
}


def hedge(obs: str, finding: str, word: str) -> str:
    tier, with_obs, no_obs = REAL_HEDGES[word]
    obs, finding = obs.strip().rstrip("."), finding.strip().rstrip(".")
    t = with_obs if obs else no_obs
    return t.format(O=obs[:1].upper() + obs[1:], F=finding, Fc=finding[:1].upper() + finding[1:])


def real_hedge_items(sources: List[dict]) -> List[dict]:
    prob = ["suspicious for", "worrisome for", "concerning for", "appears to represent"]
    poss = ["raises the possibility of", "query", "cannot be excluded"]
    out = []
    for k, s in enumerate([s for s in sources if s["dict_tier"] == "probable" and not s.get("meaning")]):
        out.append((s, prob[k % len(prob)], "same"))
        if k < 6:
            out.append((s, "raises the possibility of", "downgrade"))
    for k, s in enumerate([s for s in sources if s["dict_tier"] == "possible" and not s.get("meaning")]):
        out.append((s, poss[k % len(poss)], "same"))
        out.append((s, "suspicious for", "upgrade"))
    return [{"id": f"d-{s['sid']}-{w.replace(' ', '_')}", "set": "d", "relation": rel, "category": f"{rel}:{w}",
             "clause": hedge(s["obs"], s["finding"], w), "case_key": s["case_key"],
             "intended_tier": REAL_HEDGES[w][0]} for s, w, rel in out]


def cmd_build(_args) -> None:
    out = common.lab_out(GATE)
    gb = common.lab_out("gate_b")
    items: List[dict] = []
    for it in common.read_json(gb / "certainty_items.json"):
        c = it["case"]
        key = f"b:{it['id8']}"
        s = "a" if it["label"] == "same" else ("b" if it["category"] == "real_upgrade" else "b_synth")
        rel = "same" if it["label"] == "same" else "upgrade"
        items.append({"id": f"{s}-{it['id']}", "set": s, "relation": rel, "category": it["category"],
                      "clause": it["clause"], "case_key": key,
                      "state": {"scan": c["scan"], "history": c.get("history") or "", "dictation": c["dictation"]}})
    pool = {p["id"]: p for p in common.read_json(out / "type_pool.json")}
    for pid, lab in common.read_json(out / "hybrid_labels_c.json").items():
        p = pool[pid]
        items.append({"id": f"c-{pid}", "set": "c", "relation": lab["relation"], "category": lab["relation"],
                      "boundary": lab["boundary"], "clause": p["clause"], "case_key": f"e:{p['report_id'][:8]}"})
    items += real_hedge_items(common.read_json(out / "tier_sources.json"))
    common.write_json(out / "hybrid_items.json", items)
    print(len(items), Counter((i["set"], i["relation"]) for i in items))


def request(it: dict, cases: Dict[str, dict]) -> Dict[str, Dict[str, dict]]:
    state = it.get("state") or cases[it["case_key"]]
    c = it["clause"]
    return {_support_state(state): {
        "D2": tier_question(D2.format(c=c)),
        "D2n": {"type": "choice", "instructions": D2.format(c=c), "criteria": dict(D2N_CRITERIA)},
        "C1n": certainty_question("C1n", c)}}


async def _run(items: List[dict], path) -> None:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    cases = _cases()
    with open(path, "a") as fh:
        for it in items:
            t = time.monotonic()
            try:
                ans, _, _ = await calls.jev(request(it, cases))
                err = None
            except Exception as e:   # noqa: BLE001
                ans, err = {}, f"{type(e).__name__}: {str(e)[:200]}"
            fh.write(json.dumps({"item_id": it["id"], "answers": ans, "error": err,
                                 "latency_s": round(time.monotonic() - t, 3)}) + "\n")
            fh.flush()


def cmd_run(args) -> None:
    common.load_env()
    items = common.read_json(common.lab_out(GATE) / "hybrid_items.json")
    if args.limit:
        by_set: Dict[str, int] = {}
        keep = []
        for i in items:                       # smoke: `limit` items of every set
            if by_set.get(i["set"], 0) < args.limit:
                keep.append(i)
                by_set[i["set"]] = by_set.get(i["set"], 0) + 1
        items = keep
    path = common.out_file(GATE, f"hybrid_jev{'_smoke' if args.limit else ''}", "jsonl")
    asyncio.run(_run(items, path))
    print(path)


def decisions(it: dict, ans: dict) -> Dict[str, Optional[bool]]:
    rt = report_tier(it["clause"])
    c1 = float(ans["C1n"]["noul"]) if ans.get("C1n") else None
    return {"C1n": None if c1 is None else c1 >= 0.5,
            "hybrid_D2": flag(rt, choice_of(ans.get("D2")), c1),
            "hybrid_D2n": flag(rt, choice_of(ans.get("D2n")), c1),
            "tier_only_D2": flag(rt, choice_of(ans.get("D2")), None)}


def score(items: List[dict], rows: List[dict]) -> dict:
    by_id = {i["id"]: i for i in items}
    out: Dict[str, dict] = {}
    for r in rows:
        it = by_id.get(r["item_id"])
        if it is None or r.get("error"):
            continue
        for arm, f in decisions(it, r["answers"]).items():
            cell = out.setdefault(it["set"], {}).setdefault(arm, {}).setdefault(it["relation"], Counter())
            cell["flag" if f else ("none" if f is None else "no")] += 1
    return {s: {a: {rel: dict(c) for rel, c in v.items()} for a, v in arms.items()} for s, arms in out.items()}


def report_tier_accuracy(items: List[dict]) -> dict:
    d = [i for i in items if i["set"] == "d"]
    wrong = [(i["clause"][:80], i["intended_tier"], report_tier(i["clause"])) for i in d
             if report_tier(i["clause"]) != i["intended_tier"]]
    return {"n": len(d), "wrong": wrong}


def cmd_score(args) -> None:
    items = common.read_json(common.lab_out(GATE) / "hybrid_items.json")
    rows = common.read_jsonl(args.results)
    res = {"run1": score(items, rows), "report_tier_d": report_tier_accuracy(items),
           "latency_p50_s": sorted(r["latency_s"] for r in rows)[len(rows) // 2] if rows else None,
           "errors": sum(1 for r in rows if r.get("error"))}
    if args.results2:
        res["run2"] = score(items, common.read_jsonl(args.results2))
    print(json.dumps(res, indent=1)[:8000])
    print(common.write_json(common.out_file(GATE, "hybrid_score"), res))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int, default=0)
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score")
    s.add_argument("--results", required=True)
    s.add_argument("--results2", default="")
    s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
