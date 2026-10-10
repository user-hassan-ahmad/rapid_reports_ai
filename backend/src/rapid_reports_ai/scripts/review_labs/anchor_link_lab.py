"""Link wording lab (spec 2026-10-09 §5.1): does Jev tell whether one report sentence says a brief label?

    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab build      # stored-case pairs (scratchpad)
    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab run --runs 2 [--arms S1,C1,C2]
    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab score --results <jsonl>

Arms: S1 reads the unit alone; C1 / C2 read the previous sentence and the unit's sentence (`brief_anchor.link_state`).
Gate: 0 wrong links (P >= min on a gold-false pair) in every run; among passing (arm, min) the best recall.
Production text stays under $RR_LAB_OUT/anchor_link/."""
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
    "S1": ba.LINK_WORDING_S1,
    "C1": ('Read the LAST sentence below; any earlier sentence only shows what it refers to. '
           'It says, in any wording: "{t}".'),
    "C2": ('The last sentence below states, for the same structure, side and level, in any wording: "{t}". '
           'Earlier text is context only.'),
}
CONTEXT = {"C1", "C2"}
MINS = (0.8, 0.85, 0.9)


def pairs() -> list:
    out = common.read_json(FIXTURE)
    extra = common.lab_out("anchor_link") / "stored_pairs.json"
    return out + (common.read_json(extra) if extra.exists() else [])


def build() -> None:
    """Stored cases: every label × each of its candidate units (`brief_anchor.candidates`: the proposal's unit, the
    term-hit units, else units sharing a word) becomes a pair with the unit's sentence and the one before it. Gold
    carries over from the previous stored_pairs.json by id when the unit text is unchanged; the rest is null: label it
    by peer read in the JSON (true / false, trap where it applies)."""
    rows = common.metabase(
        "select id, candidate_reports->0->>'content' as report, candidate_reports->0->'brief'->'decisions' as d "
        "from reports where candidate_reports->0->'brief'->'decisions' is not null "
        "and created_at > now() - interval '30 days'")
    path = common.lab_out("anchor_link") / "stored_pairs.json"
    old = {p["id"]: p for p in (common.read_json(path) if path.exists() else [])}
    out = []
    for r in rows:
        d = r["d"] if isinstance(r["d"], dict) else json.loads(r["d"])   # Metabase may return jsonb as text
        if not isinstance(d, dict) or not r.get("report"):
            continue
        us = ba.units(r["report"])
        labels = ba.brief_labels(d)
        got, _ = ba.match_terms(r["report"], labels, us)
        cands = ba.candidates(r["report"], labels, us, got)
        by_ref = {lab.ref: lab for lab in labels}
        for ref, cs in cands.items():
            for n, _ in cs:
                u = us[n]
                pid = f"{str(r['id'])[:8]}:{ref}:{u.start}"
                prev = old.get(pid) if old.get(pid, {}).get("sentence") == u.text else None
                out.append({"id": pid, "label": by_ref[ref].text, "sentence": u.text, "context": u.sentence,
                            "prev": u.prev, "gold": prev["gold"] if prev else None,
                            **({"trap": prev["trap"]} if prev and prev.get("trap") else {})})
    out = list({p["id"]: p for p in out}.values())
    common.write_json(path, out)
    print(f"{len(out)} stored pairs, {sum(p['gold'] is None for p in out)} without gold; label them before `run`")


def state(arm: str, p: dict) -> str:
    """S1: the unit alone. C*: what `brief_anchor.link_state` sends (a synthetic pair without context: the sentence)."""
    if arm not in CONTEXT:
        return p["sentence"]
    return f"{p.get('prev') or ''}\n{p.get('context') or p['sentence']}".strip()


async def _one(arm: str, p: dict, sem: asyncio.Semaphore) -> dict:
    q = {"type": "noul", "instructions": ARMS[arm].format(t=p["label"].strip().rstrip(".")),
         "criteria": {"true": "the sentence says it", "false": "the sentence does not say it"}}
    async with sem:
        try:
            ans = await rc._jev(state(arm, p), {"q": q})
            return {"id": p["id"], "arm": arm, "p": float(ans["q"]["noul"])}
        except Exception as e:  # noqa: BLE001 - a failed call is recorded, scored as no link
            return {"id": p["id"], "arm": arm, "p": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}


async def run(runs: int, arms: list) -> Path:
    common.load_env()
    todo = [p for p in pairs() if p.get("gold") is not None]
    out = common.out_file("anchor_link", "results", "jsonl")
    sem = asyncio.Semaphore(8)
    with open(out, "w") as f:
        for k in range(runs):
            for arm in arms:
                for r in await asyncio.gather(*(_one(arm, p, sem) for p in todo)):
                    f.write(json.dumps({**r, "run": k}) + "\n")
    print(out)
    return out


def score(results: str) -> None:
    """Per arm × min × run: wrong links (P >= min on gold false), recall on gold true; then the passing pick."""
    gold = {p["id"]: p for p in pairs()}
    rs = [r for r in common.read_jsonl(results) if r["id"] in gold]
    arms = list(dict.fromkeys(r["arm"] for r in rs))
    runs = sorted({r["run"] for r in rs})
    best = None
    print("arm  min   " + "  ".join(f"run{k}: wrong  recall(syn+stored)" for k in runs))
    for arm in arms:
        for lo in MINS:
            cells, worst, rec_min = [], 0, None
            for k in runs:
                xs = [r for r in rs if r["arm"] == arm and r["run"] == k]
                link = [r for r in xs if r["p"] is not None and r["p"] >= lo]
                wrong = sorted(r["id"] for r in link if not gold[r["id"]]["gold"])
                pos = [r for r in xs if gold[r["id"]]["gold"]]
                hit = [r for r in link if gold[r["id"]]["gold"]]
                syn = sum(":" not in r["id"] for r in hit)
                cells.append(f"{len(wrong):>5}  {len(hit)}/{len(pos)} ({syn}+{len(hit) - syn}) {wrong[:4]}")
                worst = max(worst, len(wrong))
                rec_min = len(hit) if rec_min is None else min(rec_min, len(hit))
            print(f"{arm:4} {lo:<5} " + "  ".join(cells))
            if worst == 0 and (best is None or rec_min > best[2] or (rec_min == best[2] and lo > best[1])):
                best = (arm, lo, rec_min)
    print("pick (0 wrong in every run, best worst-run recall):", best)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "score"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--results")
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        asyncio.run(run(a.runs, a.arms.split(",")))
    else:
        score(a.results)
