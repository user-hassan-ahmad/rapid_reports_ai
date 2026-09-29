import asyncio, json, re, sys, random
from pathlib import Path
sys.path.insert(0, "/Users/hassan/Code/rapid_reports_ai/backend/src")
from dotenv import load_dotenv; load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")
from rapid_reports_ai import quick_report_brief as qb
exec(open("/Users/hassan/Code/rapid_reports_ai/backend/src/rapid_reports_ai/scripts/jev_quality_probe.py").read().split("# ── build labelled items")[0].split("random.seed(7)")[1])
Qc = "The impression mentions this finding, in any wording: "
def content(t): return set(re.findall(r"[a-z]{4,}", t.lower()))
async def main():
    res = []
    for r in rows:
        case = cases[r["case"]]; imp = section(r["report"], "IMPRESSION"); ss = sentences(imp)
        items_ = [d for d in qb.split_findings(case["findings"]) if not d.lower().startswith("no ")]
        for d in items_[:4]:
            hit = [s for s in ss if len(content(d) & content(s)) >= 2]
            if not hit: continue
            kept = " ".join(s for s in ss if s not in hit)
            qs = {"present": {"type": "noul", "instructions": Qc + d}}
            a = await qb._jev(f"IMPRESSION:\n{imp}", qs); b = await qb._jev(f"IMPRESSION:\n{kept or '(empty)'}", qs)
            res.append((float(a["present"]["noul"]), 1, d)); res.append((float(b["present"]["noul"]), 0, d))
    pos=[s for s,l,_ in res if l]; neg=[s for s,l,_ in res if not l]
    for th in (0.5, 0.7):
        print(f"carried th={th} present recognised {sum(s>=th for s in pos)}/{len(pos)}  removed caught {sum(s<th for s in neg)}/{len(neg)}")
    for s,l,d in sorted(res):
        if (s>=0.5)!=(l==1): print(f"   {s:.2f} label={l} {d[:120]}")
asyncio.run(main())
