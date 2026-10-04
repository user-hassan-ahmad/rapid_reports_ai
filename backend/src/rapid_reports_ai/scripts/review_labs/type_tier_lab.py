"""Statement-type and certainty-tier wording lab (2026-10-04; ledger L-53 / L-55 / L-57 follow-up). NOT wired into the
engine: it measures whether Jev can replace two code lexicons in `review_engine.jev_pass`.

A. Statement type: one Jev choice per report clause, report text only (abnormal / normal / mixed / not_a_finding).
   Two wordings (TA, TB). Would replace the `normal_statement` / `recommendation` regexes that gate W1n / C1n.
B. Certainty tier: two ABSOLUTE choice questions (fact / probable / possible / excluded):
   R1 on the report statement alone; D1 on the dictation state for a named finding; D2 on the dictation state with the
   report statement as the reference for "the same finding". Code compares tiers (report above dictation =
   overstated). Also C1n / C2n (certainty_lab wordings), the combined rule (C1n ≥ 0.5 AND tier upgrade) and the
   averaged score ½·(C1n + (1 − C2n)).

    RR_LAB_OUT=<scratchpad>/review_labs python -m rapid_reports_ai.scripts.review_labs.type_tier_lab pool
    ... type_tier_lab build            # needs type_labels.json + tier_sources.json (hand-written, scratchpad)
    ... type_tier_lab run --set type|tier --runs 1 [--limit 2] [--only id,id]
    ... type_tier_lab score --set type|tier --results <jsonl> [--results2 <jsonl>]

Production text stays under $RR_LAB_OUT/type_tier/. Jev calls are strictly sequential (cheap, ~0.3 s)."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

from . import common
from .certainty_lab import question as certainty_question

GATE = "type_tier"

# ── A. statement type ────────────────────────────────────────────────────────

TYPES = ("abnormal", "normal", "mixed", "not_a_finding")
TYPE_WORDINGS = {
    "TA": ('Read only this report statement: "{c}". What does it state?',
           {"abnormal": "reports a finding or abnormality",
            "normal": "a structure is normal or a finding is absent",
            "mixed": "reports a finding AND states something normal or absent",
            "not_a_finding": "technique, comparison, recommendation, communication"}),
    "TB": ('Read only this one report statement: "{c}". Classify what it says about the patient.',
           {"abnormal": "It reports at least one abnormality or finding (a possible or likely one counts), and "
                        "nothing in it is stated as normal or absent.",
            "normal": "It only says that structures are normal, intact, preserved or patent, or that findings are "
                      "absent (no ..., free of ..., without ...).",
            "mixed": "It reports an abnormality or finding AND, in the same statement, says something is normal or "
                     "absent.",
            "not_a_finding": "It is not about the patient's anatomy: the scan technique, a comparison, a "
                             "recommendation or follow-up, or a communication."}),
}


def type_question(wording: str, clause: str) -> dict:
    text, crit = TYPE_WORDINGS[wording]
    return {"type": "choice", "instructions": text.format(c=clause), "criteria": dict(crit)}


# ── B. certainty tier ────────────────────────────────────────────────────────

TIERS = ("excluded", "possible", "probable", "fact")          # ascending certainty of presence
RANK = {t: i for i, t in enumerate(TIERS)}
TIER_CRITERIA = {
    "fact": 'definite: stated as a fact with no hedge (for example "represents", "diagnostic of", or stated plainly)',
    "probable": "probable: likely, probable, consistent with, in keeping with, compatible with, or suggestive of",
    "possible": "possible: possible, may represent, cannot be excluded, query, or a question mark",
    "excluded": "excluded: stated as absent, negated or ruled out",
}
R1 = 'Read only this report statement: "{c}". How certain is its main finding (its diagnosis or conclusion, if it gives one)?'
D1 = 'How certain do the dictated findings state "{f}"?'
D2 = ('This report statement describes a finding: "{c}". How certain do the dictated findings state that same '
      'finding?')


def tier_question(text: str) -> dict:
    return {"type": "choice", "instructions": text, "criteria": dict(TIER_CRITERIA)}


def relation(dictated: str, reported: str) -> str:
    """same | upgrade (report more certain of presence than the dictation) | downgrade."""
    d, r = RANK[dictated], RANK[reported]
    return "same" if d == r else ("upgrade" if r > d else "downgrade")


# Report-side rewrites: the dictated observation and finding wording, only the hedge changes.
HEDGES = {
    "fact": {"representing": "{O}, representing {F}.", "diagnostic of": "{O}, diagnostic of {F}.",
             "plain": "{Fc}."},
    "probable": {"likely": "{O}, likely {F}.", "consistent with": "{O}, consistent with {F}.",
                 "in keeping with": "{O}, in keeping with {F}.", "compatible with": "{O}, compatible with {F}.",
                 "suggestive of": "{O}, suggestive of {F}.", "probably": "{O}, probably {F}."},
    "possible": {"possibly": "{O}, possibly {F}.", "may represent": "{O}, which may represent {F}.",
                 "cannot exclude": "{O}; {F} cannot be excluded.", "query": "{O}, query {F}."},
    "excluded": {"no": "No {F}.", "no evidence of": "No evidence of {F}."},
}
# A finding dictated with no separate observation ("possible subluxation of the hamate").
HEDGES_NO_OBS = {
    "fact": {"representing": "Appearances represent {F}.", "diagnostic of": "Appearances are diagnostic of {F}.",
             "plain": "{Fc}."},
    "probable": {"likely": "Likely {F}.", "consistent with": "Appearances are consistent with {F}.",
                 "in keeping with": "Appearances are in keeping with {F}.",
                 "compatible with": "Appearances are compatible with {F}.",
                 "suggestive of": "Appearances are suggestive of {F}.", "probably": "Probable {F}."},
    "possible": {"possibly": "Possible {F}.", "may represent": "Appearances may represent {F}.",
                 "cannot exclude": "{Fc} cannot be excluded.", "query": "Query {F}."},
    "excluded": HEDGES["excluded"],
}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def rewrite(obs: str, finding: str, tier: str, word: str) -> str:
    """The report statement at `tier` using hedge `word`, keeping the dictated observation and finding wording.
    The excluded tier denies the finding alone ("No {F}.")."""
    obs, finding = obs.strip().rstrip("."), finding.strip().rstrip(".")
    table = HEDGES if obs else HEDGES_NO_OBS
    return table[tier][word].format(O=_cap(obs), F=finding, Fc=_cap(finding))


def tier_plan(tier: str, word: str, obs: str, n_same: int = 2) -> List[Tuple[str, str, str]]:
    """(relation, report tier, hedge word): `n_same` same-tier synonym swaps (never the dictated word itself, never a
    bare restatement that would drop the observation), a one-step upgrade, a jump to fact from possible or below,
    and a one-step downgrade, where the ladder allows."""
    plan = [("same", tier, x) for x in HEDGES[tier] if x != word and not (x == "plain" and obs)][:n_same]
    if RANK[tier] < RANK["fact"]:
        up = TIERS[RANK[tier] + 1]
        plan.append(("upgrade", up, next(iter(HEDGES[up]))))
        if RANK[tier] <= RANK["possible"]:
            plan.append(("upgrade", "fact", "representing" if obs else "plain"))
    if RANK[tier] > RANK["excluded"]:
        down = TIERS[RANK[tier] - 1]
        plan.append(("downgrade", down, next(iter(HEDGES[down]))))
    return plan


def tier_items(sources: List[dict]) -> List[dict]:
    """Each source (a real dictated statement: obs, finding, dict_tier, dict_word, optional neg_finding for the
    excluded wording) → report statements with a known relation (`tier_plan`)."""
    out: List[dict] = []
    for s in sources:
        t = s["dict_tier"]
        for rel, tier, word in tier_plan(t, s.get("dict_word", ""), s["obs"], s.get("n_same", 2)):
            f = s.get("neg_finding", s["finding"]) if tier == "excluded" else s["finding"]
            out.append({"id": f"{s['sid']}-{rel}-{tier}-{word.replace(' ', '_')}", "source": s["sid"],
                        "case_key": s["case_key"], "category": f"{rel}:{t}->{tier}", "relation": rel,
                        "dict_tier": t, "report_tier": tier, "finding": s["finding"],
                        "statement": rewrite(s["obs"], f, tier, word)})
    return out


def p_choice(ans: Optional[dict], key: str) -> float:
    return float(((ans or {}).get("probabilities") or {}).get(key, 0.0))


def choice_of(ans: Optional[dict]) -> Optional[str]:
    """The argmax choice (falls back to the reported `choice`)."""
    if not ans:
        return None
    probs = ans.get("probabilities") or {}
    return max(probs, key=probs.get) if probs else ans.get("choice")


def tier_flag(report_tier: Optional[str], dict_tier: Optional[str]) -> Optional[bool]:
    if report_tier is None or dict_tier is None:
        return None
    return RANK[report_tier] > RANK[dict_tier]


def combined(c1n: float, upgrade: Optional[bool]) -> bool:
    return c1n >= 0.5 and bool(upgrade)


def averaged(c1n: float, c2n: float) -> float:
    return 0.5 * (c1n + (1.0 - c2n))


# ── scoring helpers (pure) ───────────────────────────────────────────────────

def confusion(pairs: Sequence[Tuple[str, Optional[str]]], classes: Sequence[str] = TYPES) -> Dict[str, Dict[str, int]]:
    m = {g: {p: 0 for p in list(classes) + ["none"]} for g in classes}
    for gold, pred in pairs:
        m[gold][pred if pred in classes else "none"] += 1
    return m


def type_metrics(pairs: Sequence[Tuple[str, Optional[str]]]) -> dict:
    n = len(pairs)
    acc = sum(g == p for g, p in pairs) / n if n else None
    nb = [(g, p) for g, p in pairs if g in ("normal", "abnormal")]
    nb_acc = sum(g == p for g, p in nb) / len(nb) if nb else None
    # the decision the engine needs: is the clause a positive finding worth W1n / C1n (abnormal or mixed)?
    pos = {"abnormal", "mixed"}
    gate = [(g in pos, p in pos) for g, p in pairs]
    recall = {c: (sum(1 for g, p in pairs if g == c and p == c) / sum(1 for g, _ in pairs if g == c)
                  if any(g == c for g, _ in pairs) else None) for c in TYPES}
    return {"n": n, "accuracy": acc, "normal_vs_abnormal_acc": nb_acc, "n_normal_abnormal": len(nb),
            "recall": recall, "positive_gate_acc": sum(a == b for a, b in gate) / n if n else None,
            "positive_missed": sum(1 for a, b in gate if a and not b),
            "positive_false": sum(1 for a, b in gate if b and not a),
            "confusion": confusion(pairs)}


def flag_metrics(rows: Sequence[Tuple[str, bool]]) -> dict:
    """rows of (relation, flagged). false alarms on `same`, recall on `upgrade`, flags on `downgrade`."""
    def rate(rel):
        xs = [f for r, f in rows if r == rel]
        return (sum(xs) / len(xs) if xs else None), len(xs)
    same, n_same = rate("same")
    up, n_up = rate("upgrade")
    down, n_down = rate("downgrade")
    return {"same_false_alarm": same, "n_same": n_same, "upgrade_recall": up, "n_upgrade": n_up,
            "downgrade_flagged": down, "n_downgrade": n_down}


# ── stress clauses (synthetic, any anatomy) ──────────────────────────────────

SYNTHETIC_TYPE = [
    ("The peritoneum is free of deposit.", "normal", "free_of"),
    ("The tendon maintains continuity.", "normal", "maintains"),
    ("The anterior cruciate ligament maintains its continuity throughout.", "normal", "maintains"),
    ("The portal vein is patent.", "normal", "patent"),
    ("Hepatic veins are patent.", "normal", "patent"),
    ("The airways are clear.", "normal", "clear"),
    ("Disc heights are preserved.", "normal", "preserved"),
    ("The menisci are intact.", "normal", "intact"),
    ("The kidneys enhance symmetrically.", "normal", "plain_normal"),
    ("Bone marrow signal is unremarkable.", "normal", "unremarkable"),
    ("The thyroid gland is normal in size and attenuation.", "normal", "normal_word"),
    ("No focal liver lesion.", "normal", "negative"),
    ("There is no pleural effusion or pneumothorax.", "normal", "negative"),
    ("The bowel is of normal calibre without wall thickening.", "normal", "normal_word"),
    ("The visualised lung bases are clear.", "normal", "clear"),
    ("The mass abuts the superior mesenteric vein without luminal compromise.", "mixed", "abuts_without"),
    ("The tumour contacts the portal vein over less than 180 degrees with no narrowing.", "mixed", "abuts_without"),
    ("The liver is normal apart from a 9 mm simple cyst in segment 6.", "mixed", "normal_apart_from"),
    ("The spleen is enlarged at 15 cm, with no focal lesion.", "mixed", "finding_and_negative"),
    ("A small left pleural effusion; no pneumothorax.", "mixed", "finding_and_negative"),
    ("The gallbladder contains calculi but its wall is not thickened.", "mixed", "finding_and_negative"),
    ("Mild degenerative change, otherwise unremarkable.", "mixed", "otherwise_normal"),
    ("Partial thickness tear of the supraspinatus tendon; the remaining rotator cuff tendons are intact.", "mixed",
     "finding_and_normal"),
    ("Moderate right hydronephrosis; the left kidney is normal.", "mixed", "finding_and_normal"),
    ("A 6 mm non-obstructing calculus in the left lower pole calyx without hydronephrosis.", "mixed",
     "finding_and_negative"),
    ("Small hiatus hernia; the stomach is otherwise unremarkable.", "mixed", "otherwise_normal"),
    ("Mild disc bulge at C5/6 without cord or nerve root compression.", "mixed", "finding_and_negative"),
    ("Mild cardiomegaly with no pulmonary oedema.", "mixed", "finding_and_negative"),
    ("Grade 2 sprain of the medial collateral ligament, which maintains continuity.", "mixed", "finding_and_normal"),
    ("The appendix is normal; there is a 3 cm left ovarian cyst.", "mixed", "finding_and_normal"),
    ("Diverticulosis of the sigmoid colon without diverticulitis.", "mixed", "finding_and_negative"),
    ("Severe left hydronephrosis.", "abnormal", "plain_finding"),
    ("There is a 2 cm enhancing lesion in the right kidney, likely a renal cell carcinoma.", "abnormal", "hedged"),
    ("Possible small focus of consolidation in the left lower lobe.", "abnormal", "hedged"),
    ("Appearances are in keeping with acute appendicitis.", "abnormal", "hedged"),
    ("Moderate stenosis at L4/5 with compression of the traversing nerve root.", "abnormal", "plain_finding"),
    ("The common bile duct measures 11 mm.", "abnormal", "measurement"),
    ("The ligament is thickened and of increased signal.", "abnormal", "plain_finding"),
    ("Recommend MRI liver for further characterisation.", "not_a_finding", "recommendation"),
    ("Suggest clinical correlation and follow-up CT in 3 months.", "not_a_finding", "recommendation"),
    ("Referral to the upper GI multidisciplinary team is advised.", "not_a_finding", "recommendation"),
    ("Findings were discussed with the referring clinician by telephone at 14:20.", "not_a_finding",
     "communication"),
    ("Urgent findings communicated to the on-call surgical team.", "not_a_finding", "communication"),
    ("Contrast-enhanced CT of the chest, abdomen and pelvis in the portal venous phase.", "not_a_finding",
     "technique"),
    ("Multiplanar multisequence MRI of the right knee.", "not_a_finding", "technique"),
    ("Non-contrast CT head.", "not_a_finding", "technique"),
    ("Comparison is made with the CT of 12 March.", "not_a_finding", "comparison"),
    ("No prior imaging available for comparison.", "not_a_finding", "comparison"),
    ("Images are degraded by patient motion.", "not_a_finding", "limitation"),
]


# ── commands ─────────────────────────────────────────────────────────────────

def _review_eval():
    return common.lab_out("e2e_engine") / "review_eval"


def cmd_pool(_args) -> None:
    """Every distinct clause of the 40 report runs (FINDINGS/IMPRESSION via the alignment splitter, plus the
    COMPARISON / TECHNIQUE lines), for blind labelling."""
    from rapid_reports_ai.report_review import clauses, quick_section_names
    from rapid_reports_ai.review_engine.alignment import report_clauses
    rows = [r for f in sorted(_review_eval().glob("eval_*.jsonl")) for r in common.read_jsonl(f)]
    seen, pool = set(), []
    for r in rows:
        rep = r["report"]
        found = [(c.section, c.text.strip()) for c in report_clauses(rep, quick_section_names(rep))]
        for m in re.finditer(r"(COMPARISON|TECHNIQUE):\n(.*?)(?:\n\n|\Z)", rep, re.S):
            found += [(m.group(1), t.strip()) for t in clauses(m.group(2))]
        for sec, t in found:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                pool.append({"id": f"p{len(pool)}", "report_id": r["report_id"], "section": sec, "clause": t})
    out = common.write_json(common.lab_out(GATE) / "type_pool.json", pool)
    print(len(pool), Counter(p["section"] for p in pool), out)


def _report_of() -> Dict[str, str]:
    rows = [r for f in sorted(_review_eval().glob("eval_*.jsonl")) for r in common.read_jsonl(f)]
    return {r["report_id"]: r["report"] for r in rows}


def _cases() -> Dict[str, dict]:
    """case_key → {scan, history, dictation}: gate_b cases ("b:<id8>") and the e2e cases ("e:<id8>")."""
    out = {}
    for c in common.read_json(common.lab_out("gate_b") / "cases.json"):
        out[f"b:{c['id8']}"] = {"scan": c["scan"], "history": c.get("history") or "", "dictation": c["dictation"]}
    for c in common.read_json(_review_eval() / "cases.json"):
        v = (json.loads(c["input_data"]) if isinstance(c["input_data"], str) else c["input_data"])["variables"]
        out[f"e:{c['id'][:8]}"] = {"scan": v.get("SCAN_TYPE") or "", "history": v.get("CLINICAL_HISTORY") or "",
                                   "dictation": v.get("FINDINGS") or ""}
    return out


def cmd_build(_args) -> None:
    out = common.lab_out(GATE)
    pool = {p["id"]: p for p in common.read_json(out / "type_pool.json")}
    labels = common.read_json(out / "type_labels.json")           # {pool id: {label, category}} (peer read)
    items = [{"id": k, "source": "real", "clause": pool[k]["clause"], "report_id": pool[k]["report_id"],
              "label": v["label"], "category": v.get("category", "")} for k, v in labels.items() if k in pool]
    items += [{"id": f"s{i}", "source": "synthetic", "clause": c, "report_id": None, "label": l, "category": cat}
              for i, (c, l, cat) in enumerate(SYNTHETIC_TYPE)]
    common.write_json(out / "type_items.json", items)
    print("type", len(items), Counter(i["label"] for i in items))
    srcs = common.read_json(out / "tier_sources.json")
    tiers = tier_items([s for s in srcs if not s.get("meaning")])
    tiers += [{"id": f"{s['sid']}-real", "source": s["sid"], "case_key": s["case_key"],
               "category": "upgrade:real", "relation": "upgrade", "dict_tier": s["dict_tier"],
               "report_tier": s.get("report_tier", "fact"), "finding": s["finding"], "statement": s["statement"]}
              for s in srcs if s.get("meaning")]
    common.write_json(out / "tier_items.json", tiers)
    print("tier", len(tiers), Counter(t["relation"] for t in tiers))


def _support_state(c: dict) -> str:
    return (f"SCAN TYPE: {c['scan']}\nCLINICAL HISTORY: {c.get('history') or '(none)'}\n"
            f"DICTATED FINDINGS:\n{c['dictation']}")


def type_request(it: dict, reports: Dict[str, str]) -> Dict[str, Dict[str, dict]]:
    """One request: the report state (the full report for a real clause; the clause alone for a synthetic one)."""
    rep = reports.get(it.get("report_id") or "", "") or it["clause"]
    return {f"REPORT:\n{rep}": {w: type_question(w, it["clause"]) for w in TYPE_WORDINGS}}


def tier_requests(it: dict, case: dict) -> Dict[str, Dict[str, dict]]:
    """Two requests (as jev_pass would: the report state and the dictation state)."""
    c = it["statement"]
    return {f"REPORT:\n{c}": {"R1": tier_question(R1.format(c=c))},
            _support_state(case): {"D1": tier_question(D1.format(f=it["finding"])),
                                   "D2": tier_question(D2.format(c=c)),
                                   "C1n": certainty_question("C1n", c), "C2n": certainty_question("C2n", c)}}


async def _run(kind: str, items: List[dict], runs: int, path) -> None:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    reports = _report_of() if kind == "type" else {}
    cases = _cases() if kind == "tier" else {}
    with open(path, "a") as fh:
        for run in range(1, runs + 1):
            for it in items:
                req = type_request(it, reports) if kind == "type" else tier_requests(it, cases[it["case_key"]])
                ans, err, lat = {}, None, 0.0
                for state, qs in req.items():                       # strictly sequential
                    t = time.monotonic()
                    try:
                        a, _, _ = await calls.jev({state: qs})
                        ans.update(a)
                    except Exception as e:   # noqa: BLE001
                        err = f"{type(e).__name__}: {str(e)[:200]}"
                    lat += time.monotonic() - t
                fh.write(json.dumps({"item_id": it["id"], "run": run, "answers": ans, "error": err,
                                     "latency_s": round(lat, 3), "n_requests": len(req)}) + "\n")
                fh.flush()


def cmd_run(args) -> None:
    common.load_env()
    items = common.read_json(common.lab_out(GATE) / f"{args.set}_items.json")
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    if args.limit:
        items = items[:args.limit]
    path = common.out_file(GATE, f"{args.set}_jev{'_smoke' if args.limit else ''}", "jsonl")
    asyncio.run(_run(args.set, items, args.runs, path))
    print(path)


def score_type(items: List[dict], rows: List[dict]) -> dict:
    by_id = {i["id"]: i for i in items}
    out = {}
    for w in TYPE_WORDINGS:
        pairs = [(by_id[r["item_id"]]["label"], choice_of(r["answers"].get(w))) for r in rows
                 if r["item_id"] in by_id and r["answers"].get(w)]
        out[w] = type_metrics(pairs)
        cats: Dict[str, List[bool]] = {}
        for r in rows:
            if r["item_id"] in by_id and r["answers"].get(w):
                it = by_id[r["item_id"]]
                cats.setdefault(f"{it['label']}/{it['category']}", []).append(choice_of(r["answers"][w]) == it["label"])
        out[w]["by_category"] = {k: f"{sum(v)}/{len(v)}" for k, v in sorted(cats.items())}
    return out


def tier_decisions(it: dict, ans: dict) -> Dict[str, Optional[bool]]:
    """Every arm's overstated decision for one item."""
    r1, d1, d2 = choice_of(ans.get("R1")), choice_of(ans.get("D1")), choice_of(ans.get("D2"))
    c1 = float((ans.get("C1n") or {}).get("noul", 0.0)) if ans.get("C1n") else None
    c2 = float((ans.get("C2n") or {}).get("noul", 0.0)) if ans.get("C2n") else None
    t1, t2 = tier_flag(r1, d1), tier_flag(r1, d2)
    return {"tier_R1_D1": t1, "tier_R1_D2": t2,
            "C1n": None if c1 is None else c1 >= 0.5,
            "C2n": None if c2 is None else c2 < 0.5,
            "C1n_and_tierD1": None if c1 is None else combined(c1, t1),
            "C1n_and_tierD2": None if c1 is None else combined(c1, t2),
            "avg_C1n_C2n": None if c1 is None or c2 is None else averaged(c1, c2) >= 0.5}


def score_tier(items: List[dict], rows: List[dict]) -> dict:
    by_id = {i["id"]: i for i in items}
    dec = {}
    tier_acc = {"R1": [], "D1": [], "D2": []}
    for r in rows:
        it = by_id.get(r["item_id"])
        if it is None or r.get("error"):
            continue
        for k, v in tier_decisions(it, r["answers"]).items():
            if v is not None:
                dec.setdefault(k, []).append((it["relation"], v, it["category"]))
        tier_acc["R1"].append((it["report_tier"], choice_of(r["answers"].get("R1"))))
        if it["category"] != "upgrade:real":
            tier_acc["D1"].append((it["dict_tier"], choice_of(r["answers"].get("D1"))))
            tier_acc["D2"].append((it["dict_tier"], choice_of(r["answers"].get("D2"))))
    out = {"arms": {k: {**flag_metrics([(rel, f) for rel, f, _ in v]),
                        "real_upgrade_recall": (lambda xs: sum(xs) / len(xs) if xs else None)(
                            [f for _, f, c in v if c == "upgrade:real"]),
                        "synonym_same_false_alarm": (lambda xs: sum(xs) / len(xs) if xs else None)(
                            [f for rel, f, c in v if rel == "same"])}
                    for k, v in dec.items()},
           "tier_accuracy": {k: {"acc": sum(g == p for g, p in v) / len(v) if v else None, "n": len(v),
                                 "confusion": confusion(v, TIERS)} for k, v in tier_acc.items()}}
    return out


def drift(rows1: List[dict], rows2: List[dict], keys: Sequence[str]) -> Dict[str, dict]:
    """Share of items whose argmax choice (or noul side of 0.5) changed between two runs, per question."""
    a = {r["item_id"]: r["answers"] for r in rows1 if not r.get("error")}
    b = {r["item_id"]: r["answers"] for r in rows2 if not r.get("error")}
    out = {}
    for k in keys:
        both = [i for i in a if i in b and a[i].get(k) and b[i].get(k)]

        def side(x):
            return choice_of(x) if "probabilities" in x else float(x.get("noul", 0)) >= 0.5
        changed = sum(side(a[i][k]) != side(b[i][k]) for i in both)
        out[k] = {"n": len(both), "changed": changed, "share": changed / len(both) if both else None}
    return out


def latency(rows: List[dict]) -> dict:
    xs = sorted(r["latency_s"] for r in rows if not r.get("error"))
    if not xs:
        return {}
    return {"n": len(xs), "p50_s": xs[len(xs) // 2], "p90_s": xs[int(len(xs) * 0.9)], "max_s": xs[-1],
            "requests_per_item": rows[0].get("n_requests"), "errors": sum(1 for r in rows if r.get("error"))}


def cmd_score(args) -> None:
    out_dir = common.lab_out(GATE)
    items = common.read_json(out_dir / f"{args.set}_items.json")
    rows = common.read_jsonl(args.results)
    res = {"latency": latency(rows)}
    res.update(score_type(items, rows) if args.set == "type" else score_tier(items, rows))
    if args.results2:
        rows2 = common.read_jsonl(args.results2)
        res["drift"] = drift(rows, rows2, list(TYPE_WORDINGS) if args.set == "type" else
                             ["R1", "D1", "D2", "C1n", "C2n"])
        res["run2"] = score_type(items, rows2) if args.set == "type" else score_tier(items, rows2)
    print(json.dumps(res, indent=1)[:6000])
    print(common.write_json(common.out_file(GATE, f"{args.set}_score"), res))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pool").set_defaults(fn=cmd_pool)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    r = sub.add_parser("run")
    r.add_argument("--set", choices=["type", "tier"], required=True)
    r.add_argument("--runs", type=int, default=1)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--only", default="")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score")
    s.add_argument("--set", choices=["type", "tier"], required=True)
    s.add_argument("--results", required=True)
    s.add_argument("--results2", default="")
    s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
