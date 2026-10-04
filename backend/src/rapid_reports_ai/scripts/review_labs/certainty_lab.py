"""Certainty wording lab (2026-10-04, ledger L-53 follow-up): can Jev tell a report statement that is more certain or
more severe than the dictation? Code keeps the mechanical checks (numbers, dates, priors, modality, size words, an
explicit hedge word dropped); this measures the semantic judgement.

    python -m rapid_reports_ai.scripts.review_labs.certainty_lab build
    python -m rapid_reports_ai.scripts.review_labs.certainty_lab run --runs 2 [--only id,id]
    python -m rapid_reports_ai.scripts.review_labs.certainty_lab score --results <jsonl> [--lo 0.3 --hi 0.7]

Production text stays under $RR_LAB_OUT/gate_b/. Strictly one item at a time per run (Jev only, cheap)."""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import Dict, List, Optional

from pydantic import BaseModel

from rapid_reports_ai.scripts.jev_tool_lab import calls

from . import common, metrics

_W = {
    "C1": ('Read only this one report statement: "{c}". It states a finding as more certain or more severe than the '
           'dictated findings do, for example a possibility stated as a fact, or a milder grade stated as a worse one.'),
    "C2": ('Read only this one report statement: "{c}". The dictated findings state each finding in it with at least '
           'the same certainty and the same severity, in any wording.'),
    "C3": ('Read only this one report statement: "{c}". Compare how certain and how severe it is with what the '
           'dictated findings say about the same finding.'),
}
_CHOICES = {
    "same": "It says the same as the dictation, at the same certainty and severity, in any wording.",
    "more": "It is more certain or more severe than the dictation (a possibility stated as a fact, or a worse grade).",
    "less": "It is less certain or less severe than the dictation.",
    "cant_tell": "The dictation does not say enough about this finding to compare.",
}
ARMS = ["C1n", "C2n", "C3c"]


def question(arm: str, clause: str) -> dict:
    w = arm[:2]
    if arm.endswith("c"):
        return {"type": "choice", "instructions": _W[w].format(c=clause), "criteria": dict(_CHOICES)}
    crit = ({"true": "more certain or more severe than dictated", "false": "same or less"} if w == "C1"
            else {"true": "same certainty and severity", "false": "more certain or more severe"})
    return {"type": "noul", "instructions": _W[w].format(c=clause), "criteria": crit}


def p_overstated(arm: str, ans: dict) -> float:
    """Probability the statement is overstated, whatever the wording's polarity."""
    if arm == "C1n":
        return float(ans["noul"])
    if arm == "C2n":
        return 1.0 - float(ans["noul"])
    return float((ans.get("probabilities") or {}).get("more", 0.0))


def _state(c: dict) -> str:
    return (f"SCAN TYPE: {c['scan']}\nCLINICAL HISTORY: {c.get('history') or '(none)'}\n"
            f"DICTATED FINDINGS:\n{c['dictation']}")


class Hardened(BaseModel):
    sentence: str


HARDEN_SYS = ("Rewrite this radiology report sentence so that it overstates the dictation in one way only: {how}. "
              "Keep every other word. Return only the rewritten sentence.")
_HOW = {"hedge": "state a hedged or possible finding as a definite fact (remove or harden the hedge)",
        "severity": "make the grade, severity, extent or size word one step worse than written"}


def cmd_build(_args) -> None:
    common.load_env()
    out = common.lab_out("gate_b")
    cases = {c["id8"]: c for c in common.read_json(out / "cases.json")}
    peer = {p["gid"]: p for p in common.read_json(out.parent / "peer" / "gate_b_gold.json")}
    gids = {g["gid"]: g for g in common.read_json(out.parent / "peer" / "_gids.json")}
    items = [{"id": f"r-{k}", "id8": gids[k]["id8"], "category": "real_upgrade", "label": "more",
              "clause": gids[k]["span"], "case": cases[gids[k]["id8"]]}
             for k, p in peer.items() if p["verdict"] == "unsupported" and p["kind"] == "certainty_upgrade"]
    stated = common.read_json(out / "b2_stated_candidates.json")
    for k, s in enumerate(stated):
        items.append({"id": f"s-{k}", "id8": s["id8"], "category": "same_" + s["category"], "label": "same",
                      "clause": s["clause"], "case": cases[s["id8"]]})

    async def harden():
        need = 50 - len([i for i in items if i["label"] == "more"])
        jobs, k = [], 0
        for s in stated:                                          # harden faithful clauses, alternating mode
            if len(jobs) >= need:
                break
            how = "hedge" if s["category"] == "hedged" or k % 2 == 0 else "severity"
            jobs.append((s, how))
            k += 1
        for s, how in jobs:                                       # strictly sequential
            try:
                o, _ = await calls.qwen(Hardened, HARDEN_SYS.format(how=_HOW[how]), s["clause"], False)
                sent = o.sentence.strip()
            except Exception:   # noqa: BLE001
                continue
            if sent and sent != s["clause"]:
                items.append({"id": f"h-{len(items)}", "id8": s["id8"], "category": f"synthetic_{how}",
                              "label": "more", "clause": sent, "case": cases[s["id8"]]})
    asyncio.run(harden())
    common.write_json(out / "certainty_items.json", items)
    print(len(items), Counter(i["label"] for i in items), Counter(i["category"] for i in items))


async def _run(items: List[dict], runs: int, path) -> None:
    with open(path, "a") as fh:
        for run in range(1, runs + 1):
            for it in items:
                qs = {a: question(a, it["clause"]) for a in ARMS}
                try:
                    ans, _, _ = await calls.jev({_state(it["case"]): qs})
                    err = None
                except Exception as e:   # noqa: BLE001
                    ans, err = {}, f"{type(e).__name__}: {e}"
                for a in ARMS:
                    fh.write(json.dumps({"item_id": it["id"], "run": run, "arm": a, "label": it["label"],
                                         "category": it["category"], "answer": ans.get(a), "error": err}) + "\n")
                fh.flush()


def cmd_run(args) -> None:
    common.load_env()
    items = common.read_json(common.lab_out("gate_b") / "certainty_items.json")
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    path = common.out_file("gate_b", "certainty_jev", "jsonl")
    asyncio.run(_run(items, args.runs, path))
    print(path)


def score(rows: List[dict], lo: float, hi: float) -> Dict[str, dict]:
    out = {}
    for arm in sorted({r["arm"] for r in rows if r.get("answer")}):
        r1 = [r for r in rows if r["arm"] == arm and r["run"] == 1 and r.get("answer")]
        probs = [p_overstated(arm, r["answer"]) for r in r1]
        labels = [r["label"] == "more" for r in r1]
        r2 = {r["item_id"]: p_overstated(arm, r["answer"]) for r in rows if r["arm"] == arm and r["run"] == 2 and r.get("answer")}
        by_cat: Dict[str, list] = {}
        for r, p in zip(r1, probs):
            by_cat.setdefault(r["category"], []).append((r["label"] == "more", p >= 0.5))
        out[arm] = {"auc": metrics.auc(probs, labels), "brier": metrics.brier(probs, labels),
                    "at_0.5": metrics.binary([(l, p >= 0.5) for l, p in zip(labels, probs)]),
                    "bands": metrics.errors_by_band(probs, labels, lo, hi),
                    "by_category": {k: metrics.binary(v) for k, v in by_cat.items()},
                    "max_drift": max((abs(r2[r["item_id"]] - p) for r, p in zip(r1, probs) if r["item_id"] in r2), default=None)}
    return out


def cmd_score(args) -> None:
    res = score(common.read_jsonl(args.results), args.lo, args.hi)
    print(json.dumps(res, indent=1))
    print(common.write_json(common.out_file("gate_b", "certainty_score"), res))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    r = sub.add_parser("run"); r.add_argument("--runs", type=int, default=2); r.add_argument("--only", default="")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score"); s.add_argument("--results", required=True)
    s.add_argument("--lo", type=float, default=0.3); s.add_argument("--hi", type=float, default=0.7); s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
