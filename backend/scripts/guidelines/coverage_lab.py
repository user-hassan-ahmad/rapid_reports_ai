"""Coverage lab (library spec §12.2): which systems the unchanged matcher names on real prod stack dictations.
1. export: run the SQL below through Metabase /api/dataset in the Chrome session (Cloudflare blocks scripts) and save
   the JSON response in the session scratchpad. Raw prod text never leaves the scratchpad.
2. run:  coverage_lab.py run <metabase.json> <scratchpad>   -> matches_<pid>.json + handread_<pid>.csv
3. hand read: fill handread_<pid>.csv columns correct (y/n) and expected_none (y if no system should apply).
4. summarise: coverage_lab.py summarise <handread.csv>      -> the coverage curve and the negative-control count.
SQL: select id, scan_type, units::text as units from dictation_stack_logs
     where units is not null and created_at > now() - interval '90 days' order by created_at desc limit 400"""
import asyncio
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import matcher as M  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot import registry as R  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot import tnm  # noqa: E402,F401  (tnm.sites() is the closed list for the hand read)
from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, Library  # noqa: E402


def findings(units: list[dict]) -> list[dict]:
    """The abnormal units as the frontend sends them to /match: u<id>, or u<id>.<part> for an abnormal part."""
    out = []
    for u in units:
        if u.get("heading"):
            continue
        if u.get("parts"):
            out += [{"id": f"u{u['id']}.{n}", "text": p["text"]} for n, p in enumerate(u["parts"]) if p.get("abnormal")]
        elif u.get("abnormal"):
            out.append({"id": f"u{u['id']}", "text": u["text"]})
    return out


def cases_from_metabase(body: dict) -> list[dict]:
    cols = [c["name"] for c in body["data"]["cols"]]
    out = []
    for row in body["data"]["rows"]:
        r = dict(zip(cols, row))
        fs = findings(json.loads(r["units"] or "[]"))
        if fs:
            out.append({"id": r["id"], "scan_type": r.get("scan_type") or "", "clinical_history": "", "findings": fs})
    return out


async def _match(case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        fs = [M.Finding(**f) for f in case["findings"]]
        try:
            raw = await M._call(M._prompt(case["scan_type"], case["clinical_history"], fs, ""))
            got = {M._rid(rf.id): [s.model_dump() for s in rf.systems] for rf in raw.findings}
        except Exception as ex:
            got = {"error": str(ex)[:200]}
        return {**case, "systems": got}


async def run(src: Path, out_dir: Path) -> None:
    cases = cases_from_metabase(json.loads(src.read_text()))
    sem = asyncio.Semaphore(4)
    done = await asyncio.gather(*(_match(c, sem) for c in cases))
    pid = os.getpid()
    (out_dir / f"matches_{pid}.json").write_text(json.dumps(done, indent=1))
    with open(out_dir / f"handread_{pid}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "finding", "text", "system", "version", "site", "correct", "expected_none"])
        for c in done:
            for f in c["findings"]:
                systems = c["systems"].get(f["id"], []) if isinstance(c["systems"], dict) else []
                for s in systems or [{"name": "", "version": "", "site": ""}]:
                    w.writerow([c["id"], f["id"], f["text"], s["name"], s.get("version", ""), s.get("site", ""), "", ""])
    print(f"{len(done)} cases -> {out_dir}/matches_{pid}.json, handread_{pid}.csv")


def summarise(path: Path) -> None:
    rows = list(csv.DictReader(open(path)))
    lib = Library(json.loads(BUNDLE.read_text()))
    named = [r for r in rows if r["system"] and r["correct"] == "y"]
    counts = Counter("TNM" if r["system"].strip().upper() == "TNM" else R.norm(r["system"]) for r in named)
    total, run_sum = sum(counts.values()), 0
    print(f"{total} correctly named mentions across {len(counts)} systems")
    for n, (name, k) in enumerate(counts.most_common(), 1):
        run_sum += k
        print(f"{n:>3}. {name:<40} {k:>4}  cumulative {run_sum / total:.0%}")
    applicable = [r for r in rows if r["expected_none"] == "y" and r["system"]
                  and (r["system"].strip().upper() == "TNM" or lib.find(r["system"], r["version"]) or lib.find(r["system"]))]
    print(f"negative controls with a card that could be Applied: {len(applicable)} (gate: 0)")
    for r in applicable:
        print(f"- {r['case']} {r['finding']}: {r['system']}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        asyncio.run(run(Path(sys.argv[2]), Path(sys.argv[3])))
    else:
        summarise(Path(sys.argv[2]))
