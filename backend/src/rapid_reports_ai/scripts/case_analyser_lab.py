"""Lab: Phase 1 template-grounded case analyser on the synthetic sheet-lab sets (LAB ONLY).

    uv run python -m rapid_reports_ai.scripts.case_analyser_lab --run 1 --sets cmr_cardiomyopathy,ctca

For each set in backend/tests/fixtures/sheet_lab/<set>/:

1. **Lean template sheet** built from the answer key's TEMPLATE-INTRINSIC units only (spec "Lean template
   sheet"): the Report Structure (SECTION per key section), one ``## Paragraph:`` per key paragraph, and
   the planted NORMAL, unconditional NEGATIVE, FIXED, TERM, LIST_MISSING and context-conditioned RULE
   units, written with their answer-key grammar line. Scan Context carries the scan type and the
   technique paragraph's example text (what the lean template analyser's Scan Context would state).
   **COVERS** for each findings paragraph = the structures named in its NORMAL units' brackets (split
   on commas / "and") plus the paragraph's own name split the same way (the NORMAL brackets alone are
   partial on some keys, e.g. a paragraph whose only NORMAL names one of its structures). Every
   case-dependent planted item (findings/history-conditioned RULE or NEGATIVE, IF_PRESENT) is left out
   of the sheet — those are what Phase 1 must supply.
2. **Phase 1** (``case_analyser.deliberate``) once per held-out dictation's clinical history (findings
   are not used), then ``merge_master``.
3. **Score** against the key's case-dependent planted items:
   - negatives = IF_PRESENT and conditional NEGATIVE items, matched against every accepted case
     negative (NEGATIVE or IF_PRESENT) by content-word containment (planted words found / planted
     words, light stemming) >= NEG_MATCH;
   - recommendations = findings/history-conditioned APPENDs whose text is a recommendation (keyword
     test below; interpretive and communication APPENDs are listed as excluded), matched against
     RECOMMEND units by sentence containment >= REC_TEXT_MATCH or WHEN-subject overlap
     (shared / smaller set) >= REC_COND_MATCH.
   Recall is reported per dictation and as the set union (an item counts once any of the set's
   histories produced it). "Unplanted" = accepted case negatives matching no planted item (not
   necessarily wrong: the planted set is one consultant's template). Duplicates prevented and
   placement errors come from the code checks' rejections.

--rescore <dir> re-runs the checks and scoring on a previous run's saved raw outputs (no model calls).

Outputs to the scratchpad dir given by --out (default case_lab_<run>_<pid>): per dictation raw output,
result JSON and master sheet; per set lean sheet; summary.json and summary.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[3]
FIXTURES = BACKEND / "tests" / "fixtures" / "sheet_lab"
SCRATCH = Path("/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/"
               "9e672c4e-4eef-41cc-a40f-806516ac58ef/scratchpad")


def _load_env() -> None:
    # The lab needs no database; keep the grammar module's DB import off the production driver.
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    if (BACKEND / ".env").exists():
        load_dotenv(BACKEND / ".env")
        return
    try:  # a worktree has no .env: use the main checkout's
        common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=BACKEND, text=True).strip()
        main_env = (BACKEND / common).resolve().parent / "backend" / ".env"
        if main_env.exists():
            load_dotenv(main_env)
    except Exception:
        pass


_load_env()

from rapid_reports_ai import case_analyser as ca  # noqa: E402
from rapid_reports_ai import template_sheet_grammar as g  # noqa: E402

NEG_MATCH = 0.6
REC_TEXT_MATCH = 0.5
REC_COND_MATCH = 0.6
_RECOMMENDATION = re.compile(r"\b(recommend\w*|referral|refer|suggest\w*|advis\w*|surveillance)\b", re.I)
_SCORE_STOP = frozenset("mm cm ml more larger least than greater less suggest suggests suggestive features "
                        "feature evidence appearances appearance seen".split())


# ─────────────────────────────────────────────────────────────────────────────
# Lean template sheet from an answer key
# ─────────────────────────────────────────────────────────────────────────────

def _intrinsic(p: dict) -> bool:
    cond = p.get("condition") or {}
    if p["kind"] in ("NORMAL", "FIXED", "TERM", "LIST_MISSING"):
        return True
    if p["kind"] == "NEGATIVE":
        return not cond
    if p["kind"] == "RULE":
        return p.get("effect") == "list_missing" or cond.get("source") == "context"
    return False


def _case_item(p: dict) -> str:
    """'negative' | 'recommendation' | 'excluded' | '' (template-intrinsic or other template rule)."""
    cond = p.get("condition") or {}
    if p["kind"] == "IF_PRESENT" or (p["kind"] == "NEGATIVE" and cond):
        return "negative"
    if p["kind"] == "RULE" and p.get("effect") == "append" and cond.get("source") in ("findings", "history"):
        return "recommendation" if _RECOMMENDATION.search(p.get("text") or p.get("then_text") or p["grammar"]) else "excluded"
    return ""


def _split_structures(s: str) -> List[str]:
    return [x.strip() for x in re.split(r",|\band\b", s) if x.strip()]


def lean_sheet(key: dict) -> str:
    sections = {s["name"]: s for s in key["sections"]}
    roles = {s["name"]: s["role"] for s in key["sections"]}
    by_para: Dict[str, List[dict]] = {}
    for p in key["planted"]:
        if _intrinsic(p):
            by_para.setdefault(p["paragraph"] or "", []).append(p)
    tech = [p for p in key["paragraphs"] if roles.get(p["section"]) == "technique"]
    out = [f"# Template Sheet: {key['scan_type']}", "", "## Scan Context", f"Scan type: {key['scan_type']}."]
    for p in tech:
        out.append("Technique as written in the example reports:")
        out += [ln.strip() for ln in p["normal_text"].splitlines() if ln.strip()]
    out += ["", "## Report Structure"]
    for s in key["sections"]:
        header = f'"{s["header"]}"' if s.get("header") else "none"
        out.append(f"SECTION {s['name']} | header: {header} | role: {s['role']}")
    terms = [p for p in by_para.get("", []) if p["kind"] == "TERM"]
    if terms:
        out += ["", "## Terminology"] + [p["grammar"] for p in terms]
    tech_name = tech[0]["name"] if tech else None
    for p in by_para.get("", []):  # unparagraphed FIXED goes to the technique paragraph
        if p["kind"] == "FIXED" and tech_name:
            by_para.setdefault(tech_name, []).insert(0, p)
    for para in key["paragraphs"]:
        out += ["", f"## Paragraph: {para['name']} ({para['section']})"]
        units = by_para.get(para["name"], [])
        if roles.get(para["section"]) == "findings":
            covers: List[str] = []
            for u in units:
                if u["kind"] == "NORMAL":
                    m = re.match(r"NORMAL\s*\[([^\]]+)\]", u["grammar"])
                    covers += _split_structures(m.group(1)) if m else []
            covers = list(dict.fromkeys(covers + _split_structures(para["name"].lower())))
            out.append("COVERS [" + " | ".join(f'"{c}"' for c in covers) + "]")
        out += [u["grammar"] for u in units]
    rest = [p for p in by_para.get("", []) if p["kind"] not in ("TERM", "FIXED")]
    if rest:
        out += ["", "## Report-wide"] + [p["grammar"] for p in rest]
    return "\n".join(out) + "\n"


def lean_lint(sheet: str) -> List[str]:
    """Grammar lint of the lean sheet as a stored template sheet (lean grammar, COVERS required)."""
    return [f"{e.line}: {e.reason}: {e.text[:80]}" for e in g.parse_sheet(sheet, mode="template").errors]


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def _words(text: str) -> set:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in g._content_words(text or "") if w not in _SCORE_STOP}


def _contain(planted: str, produced: str) -> float:
    p = _words(planted)
    return len(p & _words(produced)) / len(p) if p else 0.0


def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0


def _parts(negative: str) -> List[str]:
    """A bundled planted negative split into its single findings (the analyser must write them apart)."""
    parts = re.split(r",\s*|\s+or\s+|\s+and\s+no\s+|;\s*", negative)
    return [p for p in parts if _words(p)] or [negative]


def _neg_score(planted: str, produced: List[str]) -> tuple:
    """Mean over the planted negative's single findings of the best containment by any produced negative."""
    if not produced:
        return 0.0, -1
    per, best_i, best_v = [], -1, -1.0
    for part in _parts(planted):
        scores = [_contain(part, t) for t in produced]
        per.append(max(scores))
        if max(scores) > best_v:
            best_v, best_i = max(scores), max(range(len(scores)), key=scores.__getitem__)
    return sum(per) / len(per), best_i


def score_dictation(items: List[dict], res: ca.CaseResult) -> dict:
    hits = {}
    matched_case: set = set()
    for it in items:
        best, best_txt, best_para = 0.0, "", ""
        content = None
        if it["case"] == "negative":
            best, bi = _neg_score(it["text"], [pl.text for pl in res.placements])
            if bi >= 0:
                best_txt, best_para = res.placements[bi].line, res.placements[bi].paragraph
            ok = best >= NEG_MATCH
            if ok:
                for part in _parts(it["text"]):
                    matched_case.update(i for i, pl in enumerate(res.placements) if _contain(part, pl.text) >= NEG_MATCH)
        else:
            # trigger: a recommendation keyed on the same finding; content: the same recommendation.
            content = False
            for rc in res.recommendations:
                trig = _overlap(it["condition"], rc["when"])
                cont = _contain(it["text"], rc["text"])
                sc = max(trig / REC_COND_MATCH, cont / REC_TEXT_MATCH)
                if sc > best:
                    best, best_txt = sc, f'RECOMMEND {rc["tag"]} "{rc["text"]}" WHEN [findings: {rc["when"]}]'
                content = content or cont >= REC_TEXT_MATCH
            ok = best >= 1.0
        hits[it["id"]] = {"hit": ok, "score": round(best, 2), "best": best_txt, "content": content,
                          "paragraph_ok": (best_para == it["paragraph"]) if (ok and it["case"] == "negative") else None}
    reasons = Counter(why for _, why in res.rejected)
    return {
        "hits": hits,
        "unplanted": [pl.line for i, pl in enumerate(res.placements) if i not in matched_case],
        "duplicates_prevented": reasons[ca.R_DUPLICATE] + reasons[ca.R_DUPLICATE_CASE],
        "placement_errors": reasons[ca.R_NO_PARAGRAPH] + reasons[ca.R_NOT_FINDINGS],
        "rejected_by_reason": dict(reasons),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

async def run_set(name: str, out: Path, sem: asyncio.Semaphore, rescore: Path = None) -> dict:
    key = json.loads((FIXTURES / name / "answer_key.json").read_text())
    dictations = json.loads((FIXTURES / name / "dictations.json").read_text())
    sheet = lean_sheet(key)
    summary = ca.summarise_template(sheet)
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "lean_sheet.md").write_text(sheet)
    (d / "prompt_user_example.txt").write_text(ca.build_user_prompt(summary, key["scan_type"], "<history>"))
    items, excluded = [], []
    for p in key["planted"]:
        kind = _case_item(p)
        if kind in ("negative", "recommendation"):
            items.append({"id": p["id"], "case": kind, "kind": p["kind"], "paragraph": p["paragraph"],
                          "text": p.get("text") or p.get("then_text") or "",
                          "condition": (p.get("condition") or {}).get("statement") or "",
                          "finding": (re.match(r"IF_PRESENT\s*\[([^\]]+)\]", p["grammar"]) or [None, ""])[1],
                          "grammar": p["grammar"]})
        elif kind == "excluded":
            excluded.append(p["grammar"])

    async def one(dct: dict):
        if rescore:  # reuse a previous run's model output (eval economy): checks and scoring only
            prev = json.loads((rescore / name / f"{dct['id']}.result.json").read_text())
            res = ca.parse_and_check((rescore / name / f"{dct['id']}.raw.txt").read_text(), summary, sheet)
            res.ms, res.model = prev["ms"], prev["model"]
        else:
            async with sem:
                res = await ca.deliberate(sheet, summary, key["scan_type"], dct["clinical_history"])
        master = ca.merge_master(sheet, res)
        pid = dct["id"]
        (d / f"{pid}.raw.txt").write_text(res.raw)
        (d / f"{pid}.master.md").write_text(master)
        sc = score_dictation(items, res)
        rec = {"dictation": pid, "history": dct["clinical_history"], "model": res.model, "ms": res.ms,
               "usable": res.usable, "errors": res.errors, "question": res.question,
               "differentials": res.differentials, "recommendations": res.recommendations,
               "placements": [pl.__dict__ for pl in res.placements], "rejected": res.rejected,
               "master_units_after_merge": sum(1 for ln in master.splitlines() if "| origin: case" in ln),
               **sc}
        (d / f"{pid}.result.json").write_text(json.dumps(rec, indent=1))
        return rec

    recs = await asyncio.gather(*(one(x) for x in dictations))
    union = {it["id"]: any(r["hits"][it["id"]]["hit"] for r in recs) for it in items}
    return {"set": name, "scan_type": key["scan_type"], "lean_lint": lean_lint(sheet),
            "covers": {p["name"]: p["covers"] for p in summary["paragraphs"] if p["role"] == "findings"},
            "items": items, "excluded_appends": excluded, "union": union, "dictations": recs}


def render(results: List[dict]) -> str:
    L = ["# Phase 1 case analyser lab", ""]
    L.append("| set | dictation | ms | usable | diffs (yes/no/silent) | negs placed | IF_PRESENT | recs | "
             "neg recall | rec recall (trigger/content) | unplanted | dup prevented | placement err | other rejected |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in results:
        negs = [i for i in s["items"] if i["case"] == "negative"]
        recs_i = [i for i in s["items"] if i["case"] == "recommendation"]
        for r in s["dictations"]:
            vis = Counter(x["visible"] for x in r["differentials"])
            n_neg = sum(1 for p in r["placements"] if p["kind"] == "NEGATIVE")
            n_ifp = sum(1 for p in r["placements"] if p["kind"] == "IF_PRESENT")
            nh = sum(r["hits"][i["id"]]["hit"] for i in negs)
            rh = sum(r["hits"][i["id"]]["hit"] for i in recs_i)
            rc = sum(bool(r["hits"][i["id"]]["content"]) for i in recs_i)
            other = sum(v for k, v in r["rejected_by_reason"].items()
                        if k not in (ca.R_DUPLICATE, ca.R_DUPLICATE_CASE, ca.R_NO_PARAGRAPH, ca.R_NOT_FINDINGS))
            L.append(f"| {s['set']} | {r['dictation']} | {r['ms']} | {r['usable']} | "
                     f"{len(r['differentials'])} ({vis['yes']}/{vis['no']}/{vis['silent']}) | {n_neg} | {n_ifp} | "
                     f"{len(r['recommendations'])} | {nh}/{len(negs)} | {rh}/{rc}/{len(recs_i)} | {len(r['unplanted'])} | "
                     f"{r['duplicates_prevented']} | {r['placement_errors']} | {other} |")
    L += ["", "## Set union recall (item counted once any history produced it)", ""]
    for s in results:
        for kind in ("negative", "recommendation"):
            its = [i for i in s["items"] if i["case"] == kind]
            L.append(f"- {s['set']} {kind}s: {sum(s['union'][i['id']] for i in its)}/{len(its)}")
        para_ok = [r["hits"][i["id"]]["paragraph_ok"] for r in s["dictations"] for i in s["items"]
                   if r["hits"][i["id"]]["paragraph_ok"] is not None]
        if para_ok:
            L.append(f"  - matched negatives placed in the planted paragraph: {sum(para_ok)}/{len(para_ok)}")
    for s in results:
        L += ["", f"## {s['set']} — {s['scan_type']}", ""]
        if s["lean_lint"]:
            L.append(f"Lean sheet lint (COVERS stripped): {s['lean_lint']}")
        L.append("COVERS: " + "; ".join(f"{k} = {v}" for k, v in s["covers"].items()))
        L.append("")
        L.append("Planted case items:")
        for it in s["items"]:
            per = ", ".join(f"{r['dictation']}:{'HIT' if r['hits'][it['id']]['hit'] else '-'}"
                            f"({r['hits'][it['id']]['score']})" for r in s["dictations"])
            L.append(f"- {it['id']} [{it['case']}] `{it['grammar'][:150]}` — {per}")
            best = max(s["dictations"], key=lambda r: r["hits"][it["id"]]["score"])
            if best["hits"][it["id"]]["best"]:
                L.append(f"  - best: `{best['hits'][it['id']]['best'][:200]}`")
        if s["excluded_appends"]:
            L.append("Excluded APPENDs (interpretive/communication, not Phase 1 recommendations): " +
                     " | ".join(x[:100] for x in s["excluded_appends"]))
        for r in s["dictations"]:
            L += ["", f"### {r['dictation']} — {r['history']}", f"QUESTION: {r['question']}"]
            if r["errors"]:
                L.append(f"ERRORS: {r['errors']}")
            for x in r["differentials"]:
                L.append(f"- DIFF [{x['name']}] {x['tier']} VISIBLE {x['visible']} — {x['discriminator']}")
            for x in r["recommendations"]:
                L.append(f"- REC {x['tag']} \"{x['text']}\" WHEN [{x['when']}]")
            for p in r["placements"]:
                L.append(f"- PLACE [{p['paragraph']}] {p['line']}")
            for line, why in r["rejected"]:
                L.append(f"- REJECTED ({why}): {line[:180]}")
    return "\n".join(L) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default=",".join(sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())))
    ap.add_argument("--run", default="1")
    ap.add_argument("--out", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--rescore", default="", help="a previous output dir: re-check and re-score its raw outputs")
    a = ap.parse_args()
    out = Path(a.out) if a.out else SCRATCH / f"case_lab_{a.run}_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "system_prompt.txt").write_text(ca.CASE_ANALYSER_SYSTEM_PROMPT)
    sem = asyncio.Semaphore(a.concurrency)
    results = await asyncio.gather(*(run_set(s.strip(), out, sem, Path(a.rescore) if a.rescore else None) for s in a.sets.split(",") if s.strip()))
    (out / "summary.json").write_text(json.dumps(results, indent=1))
    (out / "summary.md").write_text(render(results))
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
