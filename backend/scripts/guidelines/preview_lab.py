"""Preview lab (library spec §12 next slice, item 4: the gate for Apply). Each case runs through the preview cache
live (Qwen + Jev): the first call is a cache MISS (the latency gate), the second a cache HIT (reported apart). Scored
against expected settled values, missing inputs, outcome and card state; an input in accept_missing may be asked
instead of settled ("asked, never wrong"). Friction: the asks per card (every input in `missing`, eligibility
included). At most 2 runs; output in the session scratchpad with the pid.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check
       cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py <scratchpad-dir>"""
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")   # the lab needs model keys only, never the app database
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot.library import engine  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, Library  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import _answer, _given, preview_pack  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY  # noqa: E402

CASES = Path(__file__).with_name("preview_lab_cases.json")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _pct(xs: list[int], q: float) -> int:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def _facts(e, settled: dict[str, str]) -> dict[str, str]:
    return {e.input(k).fact: v for k, v in settled.items() if e.input(k) is not None and e.input(k).fact}


def _state(e, t, missing) -> str:
    elig = {i.id for i in e.inputs if i.role == "eligibility"}
    return "does_not_apply" if t.outcome == DOES_NOT_APPLY else "check_first" if elig & set(missing) else "applies"


def check(lib: Library, cases: list[dict]) -> int:
    """Each case's expectations through the engine alone (no model call): its expected settled values, answers and
    patient map must give expect_outcome, expect_missing and expect_state."""
    bad, shared = 0, {}
    for c in cases:
        e = lib.lookup(c["pack"])
        patient = {**c.get("patient", {}), **shared.get(c.get("patient_from", ""), {})}
        given = _given(e, c.get("answered", {}), patient)
        for k, v in c["expect_settled"].items():
            x = _answer(e, e.input(k), v) if e.input(k) is not None else None
            if x is None:
                print(f"- {c['name']}: expect_settled {k}={v!r} is not a value of {e.key}")
                bad += 1
                continue
            given[k] = x
        shared[c["name"]] = _facts(e, c["expect_settled"])
        t = engine.evaluate(e, given)
        elig = [i.id for i in e.inputs if i.role == "eligibility"]
        order = elig + [i.id for i in e.inputs if i.id not in elig]
        missing = sorted(t.needed, key=order.index)
        got = (t.outcome, missing, _state(e, t, missing))
        want = (c["expect_outcome"], c["expect_missing"], c["expect_state"])
        if got != want:
            print(f"- {c['name']}: engine gives {got}; the case says {want}")
            bad += 1
    print(f"{len(cases)} cases checked, {bad} disagree")
    return 1 if bad else 0


async def one(lib: Library, c: dict, shared: dict) -> dict:
    e = lib.lookup(c["pack"])
    patient = {**c.get("patient", {}), **shared.get(c.get("patient_from", ""), {})}
    finding, findings, history = c.get("finding", ""), c["findings"], c.get("history", "")
    answered = c.get("answered", {})
    k = PC.key(e.key, finding, findings, history, answered, patient)

    def make():
        return preview_pack(e, findings, history, answered, lib.sources(e.key), finding=finding, patient=patient)
    t0 = time.perf_counter()
    p = await PC.start(k, make)
    miss = _ms(t0)
    t1 = time.perf_counter()
    await PC.start(k, make)
    hit = _ms(t1)
    settled = {s.input: s.value for s in p.settled}
    shared[c["name"]] = {s.fact: s.value for s in p.settled if s.fact}
    want, may = c["expect_settled"], set(c.get("accept_missing", []))
    outcome = (p.trace or {}).get("outcome")
    wrong_settled = {x: (settled[x], v) for x, v in want.items() if x in settled and settled[x] != v}
    unasked = [x for x in want if x not in settled and x not in may]
    asked_instead = [x for x in want if x not in settled and x in may]
    return {"name": c["name"], "pack": c["pack"], "ms_miss": miss, "ms_hit": hit, "degraded": p.degraded,
            "outcome": outcome, "expect_outcome": c["expect_outcome"], "state": p.state,
            "expect_state": c["expect_state"],
            "wrong_proposal": outcome is not None and outcome != c["expect_outcome"],
            "outcome_ok": outcome == c["expect_outcome"], "state_ok": p.state == c["expect_state"],
            "missing": p.missing, "expect_missing": c["expect_missing"], "asks": len(p.missing),
            "missing_ok": p.missing == c["expect_missing"] or bool(asked_instead),
            "wrong_settled": wrong_settled, "unasked": unasked, "asked_instead": asked_instead,
            "settled": [s.model_dump() for s in p.settled], "possible": p.possible}


async def main(out_dir: Path) -> int:
    lib = Library(json.loads(BUNDLE.read_text()))
    cases = json.loads(CASES.read_text())["cases"]
    rows, shared = [], {}
    for c in cases:                      # sequential: latency is part of the gate
        rows.append(await one(lib, c, shared))
    out = out_dir / f"preview_lab_{os.getpid()}.json"
    out.write_text(json.dumps(rows, indent=1))
    miss = [r["ms_miss"] for r in rows if not r["degraded"]]
    hit = [r["ms_hit"] for r in rows if not r["degraded"]]
    n = lambda key: sum(bool(r[key]) for r in rows)   # noqa: E731
    print(f"{len(rows)} cases -> {out}")
    print(f"wrong proposals: {n('wrong_proposal')}  wrong settled: {n('wrong_settled')}  unasked: {n('unasked')}  "
          f"outcome ok: {n('outcome_ok')}  state ok: {n('state_ok')}  missing ok: {n('missing_ok')}  "
          f"asked instead: {sum(len(r['asked_instead']) for r in rows)}  degraded: {n('degraded')}")
    print(f"MISS ms p50 {_pct(miss, 0.5)} p95 {_pct(miss, 0.95)}   HIT ms p50 {_pct(hit, 0.5)} p95 {_pct(hit, 0.95)}")
    for pack in sorted({r["pack"] for r in rows}):
        print(f"  {pack}: miss ms {sorted(r['ms_miss'] for r in rows if r['pack'] == pack)}")
    asks = [r["asks"] for r in rows]
    print(f"asks per card: mean {statistics.mean(asks):.2f} median {statistics.median(asks)} "
          f"<=2: {sum(a <= 2 for a in asks)}/{len(asks)}  distribution {sorted(Counter(asks).items())}")
    for pack in sorted({r["pack"] for r in rows}):
        xs = [r["asks"] for r in rows if r["pack"] == pack]
        print(f"  {pack}: asks mean {statistics.mean(xs):.2f} {sorted(xs)}")
    for r in rows:
        if r["wrong_proposal"] or r["wrong_settled"] or r["unasked"] or not r["state_ok"] or r["asked_instead"]:
            print(f"- {r['pack']} / {r['name']}: outcome {r['outcome']} (want {r['expect_outcome']}), state "
                  f"{r['state']} (want {r['expect_state']}), wrong {r['wrong_settled']}, unasked {r['unasked']}, "
                  f"asked instead {r['asked_instead']}, missing {r['missing']}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check(Library(json.loads(BUNDLE.read_text())), json.loads(CASES.read_text())["cases"]))
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
