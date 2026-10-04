# backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py
"""Gate A: Coverage recall (spec §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_a page            # 27-card labelling page
    python -m rapid_reports_ai.scripts.review_labs.gate_a items           # the ~72 items (50 cards + unsampled pool)
    python -m rapid_reports_ai.scripts.review_labs.gate_a run --runs 2 [--only c2,c3]
    python -m rapid_reports_ai.scripts.review_labs.gate_a read-page --results <jsonl>
    python -m rapid_reports_ai.scripts.review_labs.gate_a score --labels <json> --read <json> --results <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Dict, List, Optional

from . import common, judgement, label_page, metrics

LABEL_SET = [2, 3, 4, 5, 6, 7, 9, 11, 18, 20, 24, 25, 28, 31, 33, 35, 38, 39, 40, 42, 43, 44, 46, 47, 48, 49, 50]
KIND_MAP = {"partial": ("coverage", "partial"), "differs": ("coverage", "differs"),
            "omission": ("coverage", "absent"), "contradiction": ("accuracy", "contradicted")}
FIELDS = [{"key": "verdict", "label": "Should show as", "type": "choice",
           "options": ["action", "minor", "info", "suppress"], "required": True},
          {"key": "material", "type": "check", "label": "Material loss"},
          {"key": "note", "type": "text", "label": "Note"}]
RULES = ("action = dictated meaning lost or changed, the radiologist should fix it. minor = real but low impact. "
         "info = a speech-recognition slip the report fixed. suppress = noise (present elsewhere, no effect, misread). "
         "Tick 'Material loss' for a clinically material loss. The engine's call and the peer read appear after you choose.")


def label_card(src: dict, peer: Optional[dict]) -> dict:
    line = src["detector_line"]
    return {
        "id": f"c{src['n']}", "title": f"Card {src['n']} · {src['kind']}", "meta": f"{src['scan']} · {src['id8']}",
        "blocks": [
            {"label": "Flagged" + (" report statement" if src["kind"] == "contradiction" else " dictated line"), "text": line},
            {"label": "Nearest report sentence", "text": src.get("report_sentence") or ""},
            {"label": "Full dictation", "text": src["dictation_full"], "highlight": [line], "collapsed": True},
            {"label": "Full report", "text": src["report_full"], "highlight": [src.get("report_sentence") or ""],
             "collapsed": True},
        ],
        "hidden": [
            {"label": "v3 call", "text": f"{src.get('class')}: {src.get('issue') or ''}"},
            {"label": "Peer read (2026-10-03)",
             "text": f"{peer['verdict']}: {peer['reason']}" if peer else "not in the peer read (both reads: suppress)"},
        ],
    }


def cmd_page(_args) -> None:
    cards = {c["n"]: c for c in common.read_json(common.pipeline_scratch() / "review_cards50_v3.json")}
    out = common.lab_out("gate_a")
    peer = {p["n"]: p for f in ("blind_A.json", "blind_B.json") for p in common.read_json(out / f)}
    page_cards = [{"id": "rules", "title": "Labelling rules", "meta": "read first", "blocks": [{"label": "Rules", "text": RULES}],
                   "hidden": []}]
    page_cards += [label_card(cards[n], peer.get(n)) for n in LABEL_SET]
    p = label_page.write_page(out / "label_27.html", "Gate A · label 27 cards", "gateA-label27-v1", page_cards, FIELDS)
    print(p)


def _candidate(kind: str, text: str, evidence: Optional[dict] = None) -> dict:
    lane, k = KIND_MAP[kind]
    is_report_side = lane == "accuracy"
    return {"lane": lane, "kind": k, "detector": "jev.contradiction" if is_report_side else "jev.classify_first",
            "anchor": text if is_report_side else None, "line": None if is_report_side else text,
            "evidence": evidence or {}}


def build_items(cards: List[dict], compare: List[dict], cases: Dict[str, dict]) -> List[dict]:
    items = []
    for c in sorted(cards, key=lambda c: c["n"]):
        items.append({"id": f"c{c['n']}", "id8": c["id8"], "case": cases[c["id8"]],
                      "candidate": _candidate(c["kind"], c["detector_line"])})
    for r in compare:
        for k, u in enumerate(r.get("jev_pool_unsampled") or []):
            items.append({"id": f"u-{r['id8']}-{k}", "id8": r["id8"], "case": cases[r["id8"]],
                          "candidate": _candidate(u["kind"], u["text"])})
    return items


def _load_items() -> List[dict]:
    ps = common.pipeline_scratch()
    return build_items(common.read_json(ps / "review_cards50_v3.json"),
                       common.read_json(ps / "audit_compare" / "compare.json"), common.prod_cases())


def cmd_items(_args) -> None:
    items = _load_items()
    p = common.write_json(common.lab_out("gate_a") / "items.json", items)
    print(p, len(items))


async def _run(items: List[dict], runs: int, out_path, prompt_name: str = judgement.DEFAULT_ADJUDICATOR) -> None:
    sem = asyncio.Semaphore(8)                     # spec §7: at most 8 concurrent calls per report
    system = judgement.prompt(prompt_name)
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(it):
                r = await judgement.judge_and_verify(it["case"], [it["candidate"]], sem, system)
                return {"item_id": it["id"], "id8": it["id8"], "run": run, **r}
            for row in await asyncio.gather(*(one(it) for it in items)):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"run {run}: {len(items)} items")


def build_synthetic_items(data: List[dict]):
    """Synthetic cases -> (items, labels). Ids come from the file; id8 = id (one report per case)."""
    items, labels = [], {}
    for d in data:
        items.append({"id": d["id"], "id8": d["id"],
                      "case": {k: d.get(k, "") for k in ("scan", "dictation", "history", "report")},
                      "candidate": d["candidate"]})
        labels[d["id"]] = {"verdict": d["label"]}
    return items, labels


def cmd_run(args) -> None:
    common.load_env()
    if args.synthetic:
        items, labels = build_synthetic_items(common.read_json(args.synthetic))
        print(common.write_json(common.out_file("gate_a", "synthetic_labels"), labels))
    else:
        items = _load_items()
    if args.only:
        keep = set(args.only.split(","))
        items = [i for i in items if i["id"] in keep]
    out = common.out_file("gate_a", f"v4_{args.tag}", "jsonl")
    asyncio.run(_run(items, args.runs, out, args.prompt))
    print(out)


READ_FIELDS = [{"key": "verdict", "label": "Correct class", "type": "choice",
                "options": ["action", "minor", "info", "suppress"], "required": True},
               {"key": "fix_ok", "label": "Fix right", "type": "choice", "options": ["yes", "no", "n/a"]},
               {"key": "material", "type": "check", "label": "Material loss"},
               {"key": "note", "type": "text", "label": "Note"}]


def cmd_read_page(args) -> None:
    rows = [r for r in common.read_jsonl(args.results) if r["run"] == 1 and r.get("cls")]
    items = {i["id"]: i for i in common.read_json(common.lab_out("gate_a") / "items.json")}
    if getattr(args, "synthetic", ""):
        items.update({i["id"]: i for i in build_synthetic_items(common.read_json(args.synthetic))[0]})
    labelled = {f"c{n}" for n in LABEL_SET}
    cards = []
    for r in rows:
        if r["item_id"] in labelled or r["item_id"] not in items:
            continue
        it = items[r["item_id"]]
        c = it["candidate"]
        flagged = c.get("line") or c.get("anchor") or ""
        fix = (f"{r.get('edit_mode')}: find «{r.get('edit_find') or r.get('edit_after') or ''}» → «{r.get('edit_replace') or ''}»"
               if r.get("edit_mode") not in (None, "none") else "no edit")
        cards.append({"id": r["item_id"], "title": f"{r['item_id']} · {c['lane']}/{c['kind']}", "meta": it["case"]["scan"],
                      "blocks": [{"label": "Flagged", "text": flagged},
                                 {"label": f"v4 call: {r.get('cls')} · {r.get('kind')}", "text": f"{r.get('label')}\n{r.get('reason') or ''}"},
                                 {"label": "v4 fix", "text": fix + f"\nverified: {json.dumps(r.get('verified'))}"},
                                 {"label": "Full dictation", "text": it["case"]["dictation"], "highlight": [flagged], "collapsed": True},
                                 {"label": "Full report", "text": it["case"]["report"], "highlight": [flagged], "collapsed": True}],
                      "hidden": []})
    p = label_page.write_page(common.lab_out("gate_a") / "read_v4.html", "Gate A · read v4 output",
                              "gateA-read-v4-v1", cards, READ_FIELDS)
    print(p, len(cards))


def score(labels: dict, read: Optional[dict], rows: List[dict]) -> dict:
    merged = {**labels, **(read or {})}
    labels = {k: v for k, v in merged.items() if k != "rules" and isinstance(v, dict) and v.get("verdict")}
    runs = [{r["item_id"]: r["cls"] for r in rows if r["run"] == n and r.get("cls")} for n in (1, 2)]
    runs = [r for r in runs if r]
    report_of = {r["item_id"]: r["id8"] for r in rows}
    m = metrics.gate_a(runs, labels, report_of)
    m["pass"] = metrics.gate_a_pass(m)
    m["errors"] = sum(1 for r in rows if r.get("error"))
    m["fix_rejected_by_guards"] = sum(1 for r in rows if r["run"] == 1 and r.get("verified") and not r["verified"]["code"])
    m["unconfirmed"] = sum(1 for r in rows if r["run"] == 1 and (r.get("verified") or {}).get("unconfirmed"))
    m["disagreements"] = sorted(i for i, l in labels.items() if runs[0].get(i) and
                                (runs[0][i] in metrics.SHOWN) != (l["verdict"] in metrics.SHOWN))
    return m


def cmd_score(args) -> None:
    m = score(common.read_json(args.labels), common.read_json(args.read) if args.read else {},
              common.read_jsonl(args.results))
    p = common.write_json(common.out_file("gate_a", "score"), m)
    print(json.dumps(m, indent=1)); print(p)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("page").set_defaults(fn=cmd_page)
    sub.add_parser("items").set_defaults(fn=cmd_items)
    r = sub.add_parser("run"); r.add_argument("--runs", type=int, default=2); r.add_argument("--only", default="")
    r.add_argument("--tag", default="full"); r.add_argument("--prompt", default=judgement.DEFAULT_ADJUDICATOR); r.add_argument("--synthetic", default="")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("read-page"); rp.add_argument("--results", required=True)
    rp.add_argument("--synthetic", default=""); rp.set_defaults(fn=cmd_read_page)
    s = sub.add_parser("score"); s.add_argument("--labels", required=True); s.add_argument("--read", default="")
    s.add_argument("--results", required=True); s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
