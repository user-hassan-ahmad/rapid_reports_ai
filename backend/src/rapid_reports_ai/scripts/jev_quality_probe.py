"""Probe: can Jev run a post-generation quality check? Six text-matching questions, scored on
today's 32 arm-B reports with known and synthetic errors. Prints precision/recall per question.

Positives (should flag) are synthetic perturbations of real reports plus the 4 real fallback
contradictions. Negatives (should pass) are the real report clauses/items as generated, which
were hand-read today (no stated negative contradicted its dictation).
"""
import asyncio, json, random, re, sys, time
from pathlib import Path

sys.path.insert(0, "/Users/hassan/Code/rapid_reports_ai/backend/src")
from dotenv import load_dotenv
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")
from rapid_reports_ai import quick_report_brief as qb

random.seed(7)
OUT = Path("/Users/hassan/Code/rapid_reports_ai/backend/test_output/confirmed_negatives")
rows = json.load(open(OUT / "20260929T234805_armB_silent_staging.json")) + json.load(open(OUT / "20260929T234805_armB_varied_10.json"))
cases = {c["name"]: c for f in ["silent_staging.json", "varied_10.json"]
         for c in json.load(open(f"/Users/hassan/Code/rapid_reports_ai/backend/test_cases/{f}"))}

Q = {
    "contra": "The dictated findings state something that this report statement denies or contradicts. Statement: ",
    "reported": "The report states this dictated finding, in any wording: ",
    "carried": "The impression mentions this finding, in any wording: ",
    "history": "This report statement repeats information from the clinical history (a symptom, age or sex, test result, medication, or prior diagnosis). Statement: ",
    "unsupported": "This report statement describes an abnormal finding that the dictated findings do not report. Statement: ",
    "concord": "This report statement links the imaging findings to the patient's symptoms, presentation or clinical history. Statement: ",
}


def section(report, name):
    m = re.search(name + r":\s*(.*?)(?:\n[A-Z][A-Z /&()-]{2,}:\s*\n|\nDr |\Z)", report, re.S)
    return m.group(1).strip() if m else ""


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", text) if len(s.strip()) > 3]


def clauses(sent):
    """A negative list 'No A, B, or C' becomes 'No A' / 'No B' / 'No C'; other sentences stay whole."""
    m = re.match(r"^(No|There is no|Without)\s+(.*)$", sent.rstrip("."), re.I)
    if not m:
        return [sent]
    parts = [p.strip() for p in re.split(r",\s*(?:or\s+|and\s+)?|\s+or\s+", m.group(2)) if p.strip()]
    return [f"No {p}" for p in parts] if len(parts) > 1 else [sent]


# ── build labelled items ──────────────────────────────────────────────────────
items = {k: [] for k in Q}   # (row_idx, state_kind, text, label)
FLIP = [("dilated", "not dilated"), ("mass", "no mass"), ("right", "left"), ("left", "right")]
HISTORY_INSERTS = ["in keeping with the patient's {h}", "consistent with the reported {h}"]
FABRICATIONS = ["There is peripancreatic fat stranding.", "A 9 mm right adrenal nodule is present.",
                "There is a small left pleural effusion.", "Mild splenomegaly is noted.", "There is free intraperitoneal gas."]
CONCORD = ["These findings account for the patient's presentation.",
           "The imaging appearances explain the clinical symptoms.", "Findings are concordant with the clinical history."]

for i, r in enumerate(rows):
    case = cases[r["case"]]
    fnd, imp = section(r["report"], "FINDINGS"), section(r["report"], "IMPRESSION")
    fcl = [c for s in sentences(fnd) for c in clauses(s)]
    # contra: real clauses (clean) + synthetic contradiction of a dictated item
    for c in random.sample(fcl, min(4, len(fcl))):
        items["contra"].append((i, "dictation", c, 0))
    dict_items = qb.split_findings(case["findings"])
    if dict_items:
        d = random.choice(dict_items)
        items["contra"].append((i, "dictation", "No " + re.sub(r"^(There is|There are|A|An)\s+", "", d, flags=re.I).rstrip(".").lower() + " is identified.", 1))
    # reported: every dictated item vs full report (clean) + vs report with its sentence removed
    for d in dict_items[:4]:
        items["reported"].append((i, "report", d, 1))  # label 1 = reported (clean)
    if dict_items and len(sentences(fnd)) > 1:
        d = dict_items[0]
        w = {x for x in re.findall(r"[a-z]{4,}", d.lower())}
        kept = [s for s in sentences(fnd) if len(w & set(re.findall(r"[a-z]{4,}", s.lower()))) < max(2, len(w) // 2)]
        if len(kept) < len(sentences(fnd)):
            items["reported"].append((i, "report_minus", d, 0))
            r.setdefault("_minus", {})[d] = r["report"].replace(fnd, " ".join(kept)).replace(imp, "")
    # carried: plan carry items vs impression (clean) + vs impression with that sentence removed
    for s in sentences(imp)[:2]:
        items["carried"].append((i, "impression", s.rstrip("."), 1))
    # history: clean clauses + synthetic insert
    for c in random.sample(fcl, min(3, len(fcl))):
        items["history"].append((i, "history", c, 0))
    h = case["clinical_history"].split(".")[0].split(",")[-1].strip()[:60] or "symptoms"
    items["history"].append((i, "history", random.choice(fcl or ["The liver is normal."]).rstrip(".") + ", " + random.choice(HISTORY_INSERTS).format(h=h.lower()) + ".", 1))
    # unsupported: clean clauses + synthetic fabrication
    for c in random.sample(fcl, min(3, len(fcl))):
        items["unsupported"].append((i, "dictation", c, 0))
    items["unsupported"].append((i, "dictation", random.choice(FABRICATIONS), 1))
    # concord: impression sentences (clean) + synthetic
    for s in sentences(imp)[:2]:
        items["concord"].append((i, "history", s, 0))
    items["concord"].append((i, "history", random.choice(CONCORD), 1))
    # the four real fallback contradictions
for i, r in enumerate(rows):
    for c in r["routes"]:
        if c["tag"] == "fallback" and c["text"] in ("No intrahepatic biliary duct dilatation", "No extrahepatic biliary duct dilatation",
                                                    "No interventricular septal bowing toward the left ventricle",
                                                    "No SMV wall irregularity or tumor encasement"):
            items["contra"].append((i, "dictation", c["text"], 1))


def state_for(i, kind, text):
    r, case = rows[i], cases[rows[i]["case"]]
    if kind == "dictation":
        return f"SCAN TYPE: {case['scan_type']}\nDICTATED FINDINGS:\n{case['findings']}"
    if kind == "report":
        return f"REPORT:\n{r['report']}"
    if kind == "report_minus":
        return f"REPORT:\n{r['_minus'][text]}"
    if kind == "impression":
        return f"IMPRESSION:\n{section(r['report'], 'IMPRESSION')}"
    if kind == "history":
        return f"CLINICAL HISTORY:\n{case['clinical_history']}"


async def main():
    groups = {}
    for q, lst in items.items():
        for (i, kind, text, label) in lst:
            groups.setdefault((i, kind, text if kind == "report_minus" else ""), []).append((q, text, label))
    t0 = time.time()
    lat = []
    results = {q: [] for q in Q}
    sem = asyncio.Semaphore(6)

    async def run(key, qs):
        i, kind, _ = key
        async with sem:
            t = time.time()
            ans = await qb._jev(state_for(i, kind, qs[0][1]), {f"x{j}": {"type": "noul", "instructions": Q[q] + text} for j, (q, text, _) in enumerate(qs)})
            lat.append((time.time() - t, len(qs)))
        for j, (q, text, label) in enumerate(qs):
            results[q].append((float(ans[f"x{j}"]["noul"]), label, text, rows[i]["case"]))

    await asyncio.gather(*[run(k, v) for k, v in groups.items()])
    print(f"calls={len(lat)} wall={time.time()-t0:.1f}s  per-call median={sorted(x for x, _ in lat)[len(lat)//2]:.2f}s  max qs/call={max(n for _, n in lat)}")
    json.dump(results, open(OUT / "jev_probe.json", "w"), indent=1)
    for q, res in results.items():
        pos = [s for s, l, *_ in res if l == 1]; neg = [s for s, l, *_ in res if l == 0]
        for th in (0.5, 0.7, 0.85):
            tp = sum(s >= th for s in pos); fp = sum(s >= th for s in neg)
            print(f"{q:<12} th={th}  pos={len(pos):>3} recall={tp/len(pos) if pos else 0:.2f}  neg={len(neg):>3} "
                  f"fp={fp} precision={tp/(tp+fp) if tp+fp else 0:.2f}")
    # show errors at 0.5
    for q, res in results.items():
        errs = [(s, l, t, c) for s, l, t, c in res if (s >= 0.5) != (l == 1)]
        if errs:
            print(f"\n-- {q} errors at 0.5 ({len(errs)}):")
            for s, l, t, c in sorted(errs)[:12]:
                print(f"   {s:.2f} label={l} [{c}] {t[:150]}")

asyncio.run(main())
