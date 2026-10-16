"""Reading lab (questionnaire-card spec §9.3; Hassan 2026-10-15): can Jev, choosing among options code narrows, let
more plainly dictated values count as read without reading silence, inference or the wrong number?

Three parts, two runs each, reported with recommendations only (Hassan decides):
  yesno  real yes/no drafts (balanced pick from the real-lab settler run, gold = the independent Opus labels' `stated`
         and value) + synthetic traps. Arms: today's claim ("The FINDING states <label>: Yes", noul >= 0.8) against a
         four-way choice (stated yes / stated no / implied / not mentioned) and a three-way one (said yes / said no /
         not said in words). Read = the arm says "stated" in the drafted direction.
  sizes  every same-family number code finds in the finding is a candidate; Jev picks the lesion's overall size on
         this study, and its size on an earlier study, or none. Real: every drafted size blocked by "another number"
         in the real run; synthetic: priors, components, siblings, dimensions.
  dates  every dated sentence in the history and dictation is a candidate; Jev picks the one that dates the
         comparison study, or none. Synthetic only (spec §9.3 item 1 cases).
Real text is read from the real-lab outputs in the scratchpad and never leaves the output directory; nothing from
production is committed, and no clinical text is printed.

Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/reading_lab.py <real_lab_dir> <out_dir>
       [--runs 2] [--only yesno,sizes,dates]"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")    # model keys only, never the app database
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import jev as J  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import dates as DT  # noqa: E402
from rapid_reports_ai.jev_client import JEV_MODEL, jev_post  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES = HERE / "reading_lab_cases.json"
SETTLER, CARDS, LABELS = "settler_79052.json", "cards_81665.json", "labels_97443.json"
WHY_KIND = "yes/no and absent values are never read"
WHY_OTHER = "another number in this finding"
WHY_SEVERAL = "the finding may describe more than one lesion"
CLAIM_MIN = 0.8                       # today's CHOICE_MIN for an enum or a boolean claim
BARS = (0.6, 0.8, 0.9)
NONE = "none"
SEM = asyncio.Semaphore(4)


# ---------- Jev ----------
async def ask(state: str, questions: dict) -> dict:
    async with SEM:
        for attempt in (1, 2):
            try:
                r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions},
                                   os.environ.get("OPENROUTER_API_KEY", ""), 6.0)
                r.raise_for_status()
                return r.json()
            except Exception as ex:
                if attempt == 2:
                    return {"error": type(ex).__name__}
    return {"error": "unreachable"}


def got_choice(body: dict, key: str) -> tuple[str, float]:
    try:
        return J.choice(body, key)
    except Exception:
        return "ERROR", 0.0


def got_noul(body: dict, key: str) -> float | None:
    try:
        return J.scores(body, [key])[key]
    except Exception:
        return None


def state_of(scope: str, finding: str, findings: str, history: str) -> str:
    """The state today's confirmation uses for the input's scope (pack_preview._confirm)."""
    if scope == "lesion":
        return f"FINDING:\n{finding}"
    return f"CLINICAL HISTORY:\n{history or 'none given'}\n\nDICTATION:\n{findings}"


# ---------- yes/no ----------
LEAD = {"lesion": "The FINDING states", "patient": "The CLINICAL HISTORY or DICTATION state"}
WHERE = {"lesion": "the FINDING", "patient": "the CLINICAL HISTORY or DICTATION"}


def q_claim(scope: str, label: str, draft: bool) -> dict:
    return {"type": "noul", "instructions": f"{LEAD[scope]} {label}: {'Yes' if draft else 'No'}"}


def q_four(scope: str, label: str) -> dict:
    w = WHERE[scope]
    return {"type": "choice", "instructions": f"How does {w} deal with this item: {label}?", "criteria": {
        "stated_yes": f"{w} says in words that it is present or true.",
        "stated_no": f"{w} says in words that it is absent or not true (for example 'no ...', 'without ...', "
                     "'never ...').",
        "implied": f"{w} does not say it in words; it could only be inferred from other details or from what is "
                   "left unsaid.",
        "not_mentioned": f"{w} says nothing that bears on it."}}


def q_three(scope: str, label: str) -> dict:
    w = WHERE[scope]
    return {"type": "choice", "instructions": (f"Read {w} literally. Do its own words answer this item: {label}?"
                                               " A guess, a default, an inference or a hedged phrase ('?', "
                                               "'possible', 'cannot exclude') is not an answer in words."),
            "criteria": {"stated_yes": "Its words say yes: present or true.",
                         "stated_no": "Its words say no: absent or not true.",
                         "not_said": "Its words do not answer it either way."}}


def yesno_cases(real_dir: Path, rng: random.Random) -> list[dict]:
    lib = LB.Library(json.loads(LB.BUNDLE.read_text()))
    cards = {c["id"]: c for c in json.loads((real_dir / CARDS).read_text())}
    labels = json.loads((real_dir / LABELS).read_text())["labels"]
    pools: dict[str, list[dict]] = defaultdict(list)
    for rec in json.loads((real_dir / SETTLER).read_text()):
        c = cards.get(rec["card"])
        for k, d in (rec.get("drafts") or {}).items():
            val = d["value"]["value"]
            if not isinstance(val, bool) or c is None:
                continue
            g = next((x for x in labels[rec["card"]]["inputs"] if x["input"] == k), None)
            if g is None:
                continue
            gv = g["value"] if g["stated"] else g.get("assumed")
            match = str(gv).strip().lower() == ("yes" if val else "no")
            e = lib.lookup(c["pack"])
            i = e.input(k)
            case = {"id": f"r:{rec['card']}:{k}", "src": "real",
                    "pack": c["pack"], "input": k, "scope": i.scope, "label": i.label, "draft": val,
                    "stated": bool(g["stated"]) and match, "gold_stated": bool(g["stated"]), "match": match,
                    "boundary": bool(g.get("boundary")),
                    "state": state_of(i.scope, c["finding"], c["findings"], c["clinical_history"]),
                    "today_passed": d["why"] == [WHY_KIND]}
            pool = ("mismatch" if not match else
                    ("pass_" if case["today_passed"] else "other_") + ("stated" if g["stated"] else "silent"))
            pools[pool].append(case)
    take = {"pass_silent": 99, "mismatch": 99, "pass_stated": 20, "other_stated": 12, "other_silent": 10}
    out = []
    for pool, n in take.items():
        xs = sorted(pools[pool], key=lambda x: x["id"])
        for x in xs:
            x["pool"] = pool
        out += rng.sample(xs, n) if n < len(xs) else xs
    for s in json.loads(CASES.read_text())["yesno"]:
        hist, dic = ((s["text"].split(": ", 1)[1], "none") if s["text"].startswith("CLINICAL HISTORY:")
                     else ("none given", s["text"]))
        out.append({**{k: s[k] for k in ("id", "scope", "label", "draft", "stated")}, "src": "synthetic",
                    "pool": "synthetic", "match": True, "boundary": False,
                    "state": f"FINDING:\n{s['text']}" if s["scope"] == "lesion"
                    else f"CLINICAL HISTORY:\n{hist}\n\nDICTATION:\n{dic}"})
    return out


async def run_yesno(cases: list[dict], runs: int) -> list[dict]:
    async def one(c: dict, run: int) -> dict:
        qs = {"claim": q_claim(c["scope"], c["label"], c["draft"]), "four": q_four(c["scope"], c["label"]),
              "three": q_three(c["scope"], c["label"])}
        bodies = await asyncio.gather(*(ask(c["state"], {k: q}) for k, q in qs.items()))
        b = dict(zip(qs, bodies))
        return {"id": c["id"], "run": run, "claim": got_noul(b["claim"], "claim"),
                "four": got_choice(b["four"], "four"), "three": got_choice(b["three"], "three")}
    return await asyncio.gather(*(one(c, r) for c in cases for r in range(runs)))


def score_yesno(cases: list[dict], res: list[dict]) -> dict:
    by = {c["id"]: c for c in cases}
    arms = {"today_claim>=0.8": lambda r, c: r["claim"] is not None and r["claim"] >= CLAIM_MIN}
    for arm in ("four", "three"):
        for bar in BARS:
            arms[f"{arm}>={bar}"] = (lambda a, t: lambda r, c: r[a][0] == ("stated_yes" if c["draft"] else
                                                                          "stated_no") and r[a][1] >= t)(arm, bar)
    out = {}
    for name, read in arms.items():
        t = Counter()
        flips = 0
        per: dict[str, list[bool]] = defaultdict(list)
        for r in res:
            c = by[r["id"]]
            ok = read(r, c)
            per[r["id"]].append(ok)
            t["n"] += 1
            if ok and c["stated"]:
                t["read_right"] += 1
            if ok and not c["stated"]:
                t["read_WRONG"] += 1
                t[f"wrong_in_{c['pool']}"] += 1
            if c["stated"]:
                t["stated_total"] += 1
        flips = sum(1 for v in per.values() if len(set(v)) > 1)
        t["unstable_cases"] = flips
        out[name] = dict(t)
    errors = sum(1 for r in res if r["claim"] is None or "ERROR" in (r["four"][0], r["three"][0]))
    return {"arms": out, "jev_errors": errors, "pools": dict(Counter(c["pool"] for c in cases))}


# ---------- sizes ----------
_NUM = r"\d+(?:\.\d+)?"
_CAND = re.compile(rf"(?:{_NUM}(?=\s*(?:to|-)\s*{_NUM}\s*(?:mm|cm)\b))|(?:{_NUM}(?:\s*[x×]\s*{_NUM})*\s*(?:mm|cm)\b)",
                   re.I)


def size_candidates(text: str) -> list[dict]:
    """Every size-family measurement written in the finding (a bare number before 'to N mm' takes that unit)."""
    out = []
    for m in _CAND.finditer(text):
        s = m.group(0)
        unit = re.search(r"(mm|cm)\b", s, re.I) or re.search(r"(mm|cm)\b", text[m.end():m.end() + 20], re.I)
        first = float(re.match(_NUM, s).group(0))
        mm = first * (10 if unit and unit.group(1).lower() == "cm" else 1)
        a, b = max(0, m.start() - 30), min(len(text), m.end() + 30)
        out.append({"key": f"n{len(out)}", "text": s, "mm": round(mm, 1),
                    "context": "…" + text[a:m.start()] + "[" + s + "]" + text[m.end():b] + "…"})
    return out


def q_size(cands: list[dict], which: str, wording: int) -> dict:
    crit = {c["key"]: f"{c['text']}, as written here: {c['context']}" for c in cands}
    if which == "current":
        ins = ("Which of these measurements is the overall size of the lesion this FINDING is about, measured on "
               "this study?" if wording == 1 else
               "Each option is a measurement written in the FINDING. Which one is the size of the whole lesion on "
               "this study: not a part of it (a solid component, projection, wall or duct), not another lesion, "
               "and not a measurement from an earlier study?")
        crit[NONE] = ("None of them, or it cannot be told: the finding describes more than one lesion, or no "
                      "measurement is this lesion's own current size.")
    else:
        ins = ("Which of these measurements is this lesion's size on an earlier study?" if wording == 1 else
               "Each option is a measurement written in the FINDING. Which one is the size of this same lesion on "
               "an earlier (prior) study, as the finding reports it?")
        crit[NONE] = "None: no earlier size of this lesion is given, or it cannot be told which."
    return {"type": "choice", "instructions": ins, "criteria": crit}


def size_cases(real_dir: Path) -> list[dict]:
    cards = {c["id"]: c for c in json.loads((real_dir / CARDS).read_text())}
    out = []
    for rec in json.loads((real_dir / SETTLER).read_text()):
        for k, d in (rec.get("drafts") or {}).items():
            if WHY_OTHER not in d["why"]:
                continue
            c = cards[rec["card"]]
            v = float(d["value"]["value"])
            mm = v * 10 if k.endswith("_cm") else v
            prior = 5.0 if re.search(r"\bon prior\b|\bprevious", c["finding"], re.I) else None   # the one real prior
            out.append({"id": f"r:{rec['card']}:{k}", "src": "real",
                        "finding": c["finding"], "current": mm, "prior": prior,
                        "accept_none": WHY_SEVERAL in d["why"]})
    for s in json.loads(CASES.read_text())["sizes"]:
        out.append({**s, "src": "synthetic", "accept_none": s["current"] is None,
                    "current": s["current"], "prior": s["prior"]})
    for c in out:
        c["cands"] = size_candidates(c["finding"])
    return out


async def run_sizes(cases: list[dict], runs: int) -> list[dict]:
    async def one(c: dict, which: str, w: int, run: int) -> dict:
        if not c["cands"]:
            return {"id": c["id"], "which": which, "w": w, "run": run, "pick": NONE, "conf": 1.0, "code": "no cands"}
        body = await ask(f"FINDING:\n{c['finding']}", {"q": q_size(c["cands"], which, w)})
        k, conf = got_choice(body, "q")
        mm = next((x["mm"] for x in c["cands"] if x["key"] == k), None)
        return {"id": c["id"], "which": which, "w": w, "run": run, "pick": k, "mm": mm, "conf": conf}
    return await asyncio.gather(*(one(c, wh, w, r) for c in cases for wh in ("current", "prior") for w in (1, 2)
                                  for r in range(runs)))


def score_sizes(cases: list[dict], res: list[dict]) -> dict:
    by = {c["id"]: c for c in cases}
    out = {}
    for which in ("current", "prior"):
        for w in (1, 2):
            for bar in BARS:
                t = Counter()
                for r in (x for x in res if x["which"] == which and x["w"] == w):
                    c = by[r["id"]]
                    gold = c[which]
                    also = c.get("prior_also", []) if which == "prior" else []
                    picked = r["pick"] != NONE and r["conf"] >= bar and r["pick"] != "ERROR"
                    t["n"] += 1
                    if r["pick"] == "ERROR":
                        t["jev_error"] += 1
                    elif not picked:
                        t["none_or_low"] += 1
                        if gold is not None and not (which == "current" and c["accept_none"]):
                            t["missed"] += 1
                    elif gold is not None and abs(r["mm"] - gold) < 0.05:
                        t["right"] += 1
                    elif which == "prior" and any(abs(r["mm"] - a) < 0.05 for a in also):
                        t["other_prior"] += 1
                    else:
                        t["WRONG"] += 1
                out[f"{which} w{w} >={bar}"] = dict(t)
    return out


# ---------- dates ----------
def date_candidates(history: str, findings: str) -> list[dict]:
    out = []
    for where, text in (("history", history), ("dictation", findings)):
        for p in DT._scan(text) or []:
            a = text.rfind(".", 0, p.start) + 1
            b = text.find(".", p.end)
            sent = text[a: b + 1 if b >= 0 else len(text)].strip()
            out.append({"key": f"d{len(out)}", "text": p.text, "where": where, "sentence": sent})
    return out


def q_date(cands: list[dict], wording: int) -> dict:
    crit = {c["key"]: f"{c['text']} ({c['where']}: \"{c['sentence']}\")" for c in cands}
    crit[NONE] = ("None of them: no date of the comparison study is given, or several earlier studies are compared "
                  "and it cannot be told which one the comparison measurement comes from.")
    ins = ("Which date is the date of the earlier imaging study this report compares with?" if wording == 1 else
           "This report compares the current scan with an earlier imaging study. Which option is that earlier "
           "study's date? Not a referral, birth, surgery, biopsy or appointment date, and not the date of a "
           "different study that is not the comparison.")
    return {"type": "choice", "instructions": ins, "criteria": crit}


async def run_dates(cases: list[dict], runs: int) -> list[dict]:
    async def one(c: dict, w: int, run: int) -> dict:
        if not c["cands"]:
            return {"id": c["id"], "w": w, "run": run, "pick": NONE, "conf": 1.0, "code": "no cands"}
        body = await ask(state_of("patient", "", c["findings"], c["history"]), {"q": q_date(c["cands"], w)})
        k, conf = got_choice(body, "q")
        txt = next((x["text"] for x in c["cands"] if x["key"] == k), None)
        return {"id": c["id"], "w": w, "run": run, "pick": k, "text": txt, "conf": conf}
    return await asyncio.gather(*(one(c, w, r) for c in cases for w in (1, 2) for r in range(runs)))


def score_dates(cases: list[dict], res: list[dict]) -> dict:
    by = {c["id"]: c for c in cases}
    out = {}
    for w in (1, 2):
        for bar in BARS:
            t = Counter()
            for r in (x for x in res if x["w"] == w):
                gold = by[r["id"]]["comparison"]
                picked = r["pick"] not in (NONE, "ERROR") and r["conf"] >= bar
                t["n"] += 1
                if r["pick"] == "ERROR":
                    t["jev_error"] += 1
                elif not picked:
                    t["right_none" if gold is None else "missed"] += 1
                elif gold is not None and r["text"] == gold:
                    t["right"] += 1
                else:
                    t["WRONG"] += 1
            out[f"w{w} >={bar}"] = dict(t)
    return out


# ---------- main ----------
def table(title: str, rows: dict) -> str:
    keys = sorted({k for v in rows.values() for k in v}, key=lambda k: (k != "n", k))
    lines = [f"\n## {title}", "| arm | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    lines += [f"| {a} | " + " | ".join(str(v.get(k, 0)) for k in keys) + " |" for a, v in rows.items()]
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("real_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--only", default="yesno,sizes,dates")
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    pid, parts, report = os.getpid(), a.only.split(","), []
    if "yesno" in parts:
        cases = yesno_cases(a.real_dir, random.Random(20261015))
        res = await run_yesno(cases, a.runs)
        sc = score_yesno(cases, res)
        (a.out_dir / f"yesno_{pid}.json").write_text(json.dumps({"cases": cases, "results": res, "score": sc}, indent=1))
        report.append(table(f"yes/no ({len(cases)} cases x {a.runs} runs; pools {sc['pools']}; "
                            f"jev errors {sc['jev_errors']})", sc["arms"]))
    if "sizes" in parts:
        cases = size_cases(a.real_dir)
        res = await run_sizes(cases, a.runs)
        sc = score_sizes(cases, res)
        (a.out_dir / f"sizes_{pid}.json").write_text(json.dumps({"cases": cases, "results": res, "score": sc}, indent=1))
        report.append(table(f"sizes ({len(cases)} cases x {a.runs} runs)", sc))
    if "dates" in parts:
        cases = json.loads(CASES.read_text())["dates"]
        for c in cases:
            c["cands"] = date_candidates(c["history"], c["findings"])
        res = await run_dates(cases, a.runs)
        sc = score_dates(cases, res)
        (a.out_dir / f"dates_{pid}.json").write_text(json.dumps({"cases": cases, "results": res, "score": sc}, indent=1))
        report.append(table(f"dates ({len(cases)} cases x {a.runs} runs)", sc))
    path = a.out_dir / f"report_{pid}.md"
    path.write_text("\n".join(report) + "\n")
    print("\n".join(report))
    print(f"\n-> {path}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
