"""Brief labeller lab (spec 2026-10-09 §5.0): today's keep / contradicted / expected labeller vs the four-label scheme
(dictated / default / implicated / contradicted, plus expected; QWEN_SYS_FULL), on stored cases (gold by peer read, in
$RR_LAB_OUT/brief_labels/) and synthetic cases (fixtures/brief_labels_cases.json).

    python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab build    # stored cases → stored_cases.json (gold null)
    python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab run --runs 2
    python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab score --results <jsonl>

One Qwen call per case per arm per run, the brief's request shape (SCAN TYPE + DICTATED FINDINGS, no normals or
measurements). Gate: contradicted recall (full) >= contradicted recall (today); dictated recognised >= 95%; 0 dictated
labelled contradicted; implicated vs default reported for the peer read. Production text stays under $RR_LAB_OUT.

Result 2026-10-09 (12 synthetic + 8 stored cases, 142 negatives, 2 runs, identical at temperature 0): full beats today on
contradicted recall (30/32 vs 29/32) and recognises every dictated negative (13/13, 0 → contradicted), but labels only
7/58 implicated negatives implicated (47 → default, 3 → dictated incl. a hedge dropped, 1 → contradicted). The review
engine shows the brief's default as green and implicated as amber, so the flag stays off until implicated recall is
fixed."""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from rapid_reports_ai import report_reconcile as rc

from . import common

GATE = "brief_labels"
FIXTURE = Path(__file__).parent / "fixtures" / "brief_labels_cases.json"
KEEP_AS = {"keep": "default"}   # today's labeller has no dictated / implicated: keep counts as default (both arms)


def _stored_path() -> Path:
    return common.lab_out(GATE) / "stored_cases.json"


def cases() -> list:
    out = [{**c, "source": "synthetic"} for c in common.read_json(FIXTURE)]
    if _stored_path().exists():
        out += [{**c, "source": "stored"} for c in common.read_json(_stored_path())]
    return out


def build() -> None:
    rows = common.metabase(
        "select id::text as id, input_data->'variables'->>'FINDINGS' as dictation, "
        "coalesce(input_data->'variables'->>'SCAN_TYPE', input_data->>'extracted_scan_type') as scan, "
        "candidate_reports->0->'brief'->'decisions'->'negatives' as negs from reports "
        "where candidate_reports->0->'brief'->'decisions'->'negatives' is not null "
        "and created_at > now() - interval '30 days' order by created_at")
    out = []
    for r in rows:
        negs = r["negs"] if isinstance(r["negs"], list) else json.loads(r["negs"] or "[]")
        if not negs or not r["dictation"]:
            continue
        out.append({"id": r["id"][:8], "scan": r["scan"] or "", "dictation": r["dictation"],
                    "negatives": [[n["text"], None] for n in negs],
                    "prod_action": [n.get("action") for n in negs]})
    common.write_json(_stored_path(), out)
    print(f"{len(out)} stored cases → {_stored_path()}; set gold per negative by peer read before `run`")


async def _arm(state: str, negs: list, full: bool) -> dict:
    try:
        qw = await rc._qwen(state, negs, [], [], full=full)
    except Exception as e:  # a timeout or schema failure scores as no label, never as a retry
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    return {d.index: d.action for d in qw.negatives}


async def run(runs: int, only: str | None) -> Path:
    common.load_env()
    out = common.out_file(GATE, "results", "jsonl")
    with open(out, "w") as f:
        for k in range(runs):
            for c in cases():
                if (only and c["source"] != only) or any(g is None for _, g in c["negatives"]):
                    continue
                state = f"SCAN TYPE: {c['scan']}\nDICTATED FINDINGS:\n{c['dictation']}"
                negs = [t for t, _ in c["negatives"]]
                res = await asyncio.gather(*(_arm(state, negs, full) for full in (False, True)))
                for arm, got in zip(("today", "full"), res):
                    if "error" in got:
                        print(c["id"], arm, got["error"])
                    for i, (_, g) in enumerate(c["negatives"]):
                        f.write(json.dumps({"case": c["id"], "source": c["source"], "arm": arm, "run": k, "i": i,
                                            "gold": g, "got": got.get(i)}) + "\n")
                f.flush()
    print(out)
    return out


def _got(r: dict) -> str | None:
    return KEEP_AS.get(r["got"], r["got"])


def _line(rs: list) -> str:
    contra = [r for r in rs if r["gold"] == "contradicted"]
    dic = [r for r in rs if r["gold"] == "dictated"]
    imp = [r for r in rs if r["gold"] in ("implicated", "default")]
    keep = sum(r["got"] == "keep" for r in rs)
    return (f"contradicted recall {sum(_got(r) == 'contradicted' for r in contra)}/{len(contra)}; "
            f"dictated recognised {sum(_got(r) == 'dictated' for r in dic)}/{len(dic)}; "
            f"dictated→contradicted {sum(_got(r) == 'contradicted' for r in dic)}; "
            f"implicated/default agreement {sum(_got(r) == r['gold'] for r in imp)}/{len(imp)}; "
            f"raw keep {keep}; no label {sum(r['got'] is None for r in rs)}")


def score(results: list) -> None:
    rows = [r for p in results for r in common.read_jsonl(p)]
    texts = {(c["id"], i): t for c in cases() for i, (t, _) in enumerate(c["negatives"])}
    for arm in ("today", "full"):
        rs = [r for r in rows if r["arm"] == arm]
        print(f"\n== {arm}")
        for src in ("synthetic", "stored"):
            sub = [r for r in rs if r["source"] == src]
            if sub:
                print(f"  {src:9s} {_line(sub)}")
        print(f"  combined  {_line(rs)}")
        print(f"  confusion {Counter((r['gold'], _got(r)) for r in rs if _got(r) != r['gold']).most_common(8)}")
        if arm == "full":
            print("  disagreements (gold → got):")
            for r in sorted(rs, key=lambda r: (r["case"], r["i"], r["run"])):
                if _got(r) != r["gold"]:
                    t = texts.get((r["case"], r["i"]), "?")
                    print(f"    {r['case']} run{r['run']} {t}: {r['gold']} → {_got(r)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "score"])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", choices=["synthetic", "stored"])
    ap.add_argument("--results", action="append", default=[])
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        asyncio.run(run(a.runs, a.only))
    else:
        score(a.results)
