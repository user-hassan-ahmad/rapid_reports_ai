"""Post-generation check, offline evaluation (ledger L-47).

Runs run_quality_check on the 32 L-45 rerun reports as generated (clean) and on a perturbed copy
of each: even rows get a contradiction injected (a dictated positive finding negated), odd rows
lose the FINDINGS sentence carrying a dictated finding. The 4 known bad fallback options are
offered on their cases. Everything is saved for hand reading.

    poetry run python -m rapid_reports_ai.scripts.quality_check_eval
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND / ".env")

from rapid_reports_ai import quick_report_quality as qq  # noqa: E402

OUT = BACKEND / "test_output" / "confirmed_negatives"
RUNS = ["20260929T234805_armB_silent_staging.json", "20260929T234805_armB_varied_10.json"]
CASES = {c["name"]: c for f in ("silent_staging.json", "varied_10.json")
         for c in json.loads((BACKEND / "test_cases" / f).read_text())}
BAD_OPTIONS = {"prod_jaundice_panc_head": ["No intrahepatic biliary duct dilatation.", "No extrahepatic biliary duct dilatation."],
               "ctpa_acute_pe_rv_strain": ["No interventricular septal bowing toward the left ventricle."],
               "ct_pancreatic_ca_staging": ["No SMV wall irregularity or tumor encasement."]}


def words(t: str) -> set:
    return set(re.findall(r"[a-z]{4,}", t.lower()))


def perturb(i: int, report: str, findings: str):
    fnd, _ = qq.report_sections(report)
    items = [t for t in qq.positive_items(findings) if len(words(t)) >= 2]
    if not items or not fnd:
        return None
    item = items[0]
    sents = qq._sentences(fnd)
    if i % 2 == 0:
        bad = "No " + re.sub(r"^(there is|there are|a|an)\s+", "", item, flags=re.I).rstrip(".").lower() + " is identified."
        return {"kind": "contradiction", "item": item, "marker": bad,
                "report": report.replace(sents[0], sents[0] + " " + bad, 1)}
    hit = [s for s in sents if len(words(item) & words(s)) >= max(2, len(words(item)) // 2)]
    if not hit or len(hit) == len(sents):
        return None
    return {"kind": "omission", "item": item, "marker": hit[0], "report": report.replace(hit[0], "", 1)}


async def one(i: int, r: dict, sem: asyncio.Semaphore) -> dict:
    case = CASES[r["case"]]
    opts = [{"id": f"fn{k}", "kind": "finding_negative", "sentence": s} for k, s in enumerate(r["offered"])]
    opts += [{"id": f"bad{k}", "kind": "finding_negative", "sentence": s} for k, s in enumerate(BAD_OPTIONS.get(r["case"], []))]
    async with sem:
        t = time.time()
        clean_rep, clean_opts, clean_tel = await qq.run_quality_check(r["report"], case["findings"], case["scan_type"], opts)
        clean_s = time.time() - t
        p = perturb(i, r["report"], case["findings"])
        pert = None
        if p:
            rep, _, tel = await qq.run_quality_check(p["report"], case["findings"], case["scan_type"], [])
            fixed = (p["marker"] not in rep) if p["kind"] == "contradiction" else \
                    any(len(words(p["item"]) & words(s)) >= max(2, len(words(p["item"])) // 2) for s in qq._sentences(qq.report_sections(rep)[0]))
            pert = {**p, "after": rep, "tel": tel, "fixed": fixed}
    return {"case": r["case"], "run": r.get("run"), "clean_before": r["report"], "clean_after": clean_rep,
            "clean_tel": clean_tel, "clean_s": round(clean_s, 2),
            "options_in": [o["sentence"] for o in opts], "options_out": [o["sentence"] for o in clean_opts],
            "perturbed": pert}


async def main() -> None:
    rows = [r for f in RUNS for r in json.loads((OUT / f).read_text())]
    sem = asyncio.Semaphore(4)
    res = await asyncio.gather(*[one(i, r, sem) for i, r in enumerate(rows)])
    path = OUT / f"{datetime.now():%Y%m%dT%H%M%S}_quality_check_eval.json"
    path.write_text(json.dumps(res, indent=1))
    changed = [x for x in res if x["clean_after"] != x["clean_before"]]
    flags = sum(len(x["clean_tel"].get("flags", [])) for x in res)
    dropped = sum(len(x["clean_tel"].get("options_dropped", [])) for x in res)
    bad_total = sum(len(v) for v in BAD_OPTIONS.values()) * 1
    bad_dropped = sum(1 for x in res for s in BAD_OPTIONS.get(x["case"], []) if s not in x["options_out"])
    pert = [x["perturbed"] for x in res if x["perturbed"]]
    lat = sorted(x["clean_s"] for x in res)
    print(f"clean reports: {len(res)}  with flags: {sum(1 for x in res if x['clean_tel'].get('flags'))}  flags: {flags}  "
          f"edited: {len(changed)}  errors: {sum(1 for x in res if x['clean_tel'].get('error'))}")
    print(f"options dropped: {dropped}  known-bad dropped: {bad_dropped}/{sum(len(BAD_OPTIONS.get(x['case'], [])) for x in res)}")
    for k in ("contradiction", "omission"):
        ps = [p for p in pert if p["kind"] == k]
        print(f"perturbed {k}: {len(ps)}  flagged: {sum(1 for p in ps if p['tel'].get('flags'))}  fixed: {sum(p['fixed'] for p in ps)}")
    print(f"clean latency median {lat[len(lat)//2]:.2f}s  max {lat[-1]:.2f}s")
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
