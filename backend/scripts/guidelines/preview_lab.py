"""Preview lab (library spec §12.3): each case through preview_pack live (Qwen + Jev), scored against its expected
settled inputs, missing inputs and outcome. At most 2 runs; output in the session scratchpad with the pid.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py <scratchpad-dir>"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")   # the lab needs model keys only, never the app database
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, Library  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import preview_pack  # noqa: E402

CASES = Path(__file__).with_name("preview_lab_cases.json")


async def one(lib: Library, c: dict) -> dict:
    e = lib.lookup(c["pack"])
    t0 = time.perf_counter()
    p = await preview_pack(e, c["findings"], c.get("history", ""), {})
    ms = int((time.perf_counter() - t0) * 1000)
    settled = {s.input: s.value for s in p.settled}
    outcome = (p.trace or {}).get("outcome")
    wrong_settled = {k: (settled.get(k), v) for k, v in c.get("expect_settled", {}).items() if settled.get(k) != v}
    return {"name": c["name"], "pack": c["pack"], "ms": ms, "outcome": outcome, "expect_outcome": c["expect_outcome"],
            "wrong_proposal": outcome is not None and outcome != c["expect_outcome"],
            "outcome_ok": outcome == c["expect_outcome"], "missing": p.missing, "expect_missing": c["expect_missing"],
            "missing_ok": p.missing == c["expect_missing"], "wrong_settled": wrong_settled,
            "settled": [s.model_dump() for s in p.settled], "possible": p.possible}


async def main(out_dir: Path) -> int:
    lib = Library(json.loads(BUNDLE.read_text()))
    cases = json.loads(CASES.read_text())["cases"]
    rows = []
    for c in cases:                      # sequential: latency is part of the gate
        rows.append(await one(lib, c))
    out = out_dir / f"preview_lab_{os.getpid()}.json"
    out.write_text(json.dumps(rows, indent=1))
    ms = sorted(r["ms"] for r in rows)
    p95 = ms[min(len(ms) - 1, int(0.95 * len(ms)))]
    print(f"{len(rows)} cases -> {out}")
    print(f"wrong proposals: {sum(r['wrong_proposal'] for r in rows)}  outcome ok: {sum(r['outcome_ok'] for r in rows)}"
          f"  missing ok: {sum(r['missing_ok'] for r in rows)}  settled clean: {sum(not r['wrong_settled'] for r in rows)}")
    print(f"latency ms p50 {ms[len(ms) // 2]}  p95 {p95}")
    for r in rows:
        if r["wrong_proposal"] or not r["missing_ok"] or r["wrong_settled"]:
            print(f"- {r['pack']} / {r['name']}: outcome {r['outcome']} (want {r['expect_outcome']}), "
                  f"missing {r['missing']} (want {r['expect_missing']}), settled diffs {r['wrong_settled']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
