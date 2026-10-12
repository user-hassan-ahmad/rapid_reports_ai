"""Preview lab (library spec §12 next slice, item 4: the gate for Apply; strengthened in the lab fix round, item 6).
Each case runs live (Qwen + Jev) through the preview cache and pack_preview.settle_pack / finish.

Ground truth: every case carries `truth`, a value for every input of its pack (as a radiologist would answer it).
After the preview, every asked input is filled from `truth` (repeatedly, as answers open new inputs) and the card is
evaluated by the engine alone. Every settled value is compared with `truth`: one that disagrees is a WRONG VALUE.
The outcome the preview proposes before any answer, and the final outcome after the fill, are compared with
`expect_final` (the engine on `truth` alone): a mismatch is a WRONG PROPOSAL.

Latency scenarios, fixed before any run, each reported separately (milliseconds, over every row; degraded rows
(a model or Jev failure or timeout) are also reported apart, and a degraded (b) open counts as over the bar):
  (a) cold open: an empty cache, the settlement computed on open (MISS); always reported;
  (b) open 2 s after /match, with the prewarm started by /match still running or done;
  (c) open after more dictation: prewarmed at /match, then the dictation grows before open (a new key: a MISS);
  (d) the answer path: each fill step (engine only; no model, no Jev).
Gate: 0 wrong values, 0 wrong proposals, and (b) p95 under 2000 ms. If (b) passes and (a) does not, the gate
passes with "cold open slow" flagged for Hassan.

Friction: the asks per card before any answer (every input in `missing`, eligibility included). At most 2 runs;
output in the session scratchpad with the pid.
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
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import (  # noqa: E402
    Settlement, _answer, _given, finish, settle_pack)
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY  # noqa: E402

CASES = Path(__file__).with_name("preview_lab_cases.json")
GATE_B_MS = 2000
OPEN_DELAY_S = 2.0                     # scenario (b) and (c): the card is opened this long after /match
MORE_DICTATION = " The remaining imaged structures are unremarkable."   # scenario (c): dictation after /match
MAX_FILL = 10                          # fill rounds: answers may open new inputs


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def _pct(xs: list[float], q: float) -> int:
    xs = sorted(xs)
    return int(xs[min(len(xs) - 1, int(q * len(xs)))]) if xs else 0


def _facts(e, settled: dict[str, str]) -> dict[str, str]:
    return {e.input(k).fact: v for k, v in settled.items() if e.input(k) is not None and e.input(k).fact}


def _state(e, t, missing) -> str:
    elig = {i.id for i in e.inputs if i.role == "eligibility"}
    return "does_not_apply" if t.outcome == DOES_NOT_APPLY else "check_first" if elig & set(missing) else "applies"


def _same(e, k: str, a: str, b: str) -> bool:
    """Two answers to one input mean the same value ("12 mm" and "1.2 cm"; "Yes" and "Yes")."""
    i = e.input(k)
    x, y = _answer(e, i, a), _answer(e, i, b)
    return x is not None and y is not None and x.model_dump() == y.model_dump()


def _truth_given(e, truth: dict[str, str]) -> dict:
    return {k: _answer(e, e.input(k), v) for k, v in truth.items()}


def check(lib: Library, cases: list[dict]) -> int:
    """No model call. Each case's expectations through the engine alone: its expected settled values, answers and
    patient map must give expect_outcome, expect_missing and expect_state; its truth must cover every input of the
    pack with a value the pack can take, agree with every expected settled value and answer, and give expect_final."""
    bad, shared = 0, {}

    def no(c, msg):
        nonlocal bad
        print(f"- {c['name']}: {msg}")
        bad += 1
    for c in cases:
        e = lib.lookup(c["pack"])
        patient = {**c.get("patient", {}), **shared.get(c.get("patient_from", ""), {})}
        given = _given(e, c.get("answered", {}), patient)
        for k, v in c["expect_settled"].items():
            x = _answer(e, e.input(k), v) if e.input(k) is not None else None
            if x is None:
                no(c, f"expect_settled {k}={v!r} is not a value of {e.key}")
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
            no(c, f"engine gives {got}; the case says {want}")
        truth = c.get("truth", {})
        if set(truth) != {i.id for i in e.inputs}:
            no(c, f"truth does not cover every input: missing {sorted({i.id for i in e.inputs} - set(truth))}, "
                  f"unknown {sorted(set(truth) - {i.id for i in e.inputs})}")
            continue
        tg = _truth_given(e, truth)
        if any(v is None for v in tg.values()):
            no(c, f"truth values the pack cannot take: {[k for k, v in tg.items() if v is None]}")
            continue
        for src in (c["expect_settled"], c.get("answered", {}),
                    {i.id: patient[i.fact] for i in e.inputs if i.fact and i.fact in patient}):
            for k, v in src.items():
                if not _same(e, k, v, truth[k]):
                    no(c, f"{k}={v!r} disagrees with truth {truth[k]!r}")
        final = engine.evaluate(e, tg).outcome
        if final is None or final != c.get("expect_final"):
            no(c, f"truth gives {final!r}; expect_final is {c.get('expect_final')!r}")
        if c["expect_outcome"] is not None and c["expect_outcome"] != final:
            no(c, f"expect_outcome {c['expect_outcome']!r} is not the truth's outcome {final!r}")
    print(f"{len(cases)} cases checked, {bad} disagree")
    return 1 if bad else 0


def _fill(e, s, c: dict, patient: dict) -> tuple[object, list[float], dict]:
    """Answer every asked input from truth until nothing is asked (or nothing changes): engine only."""
    answered = dict(c.get("answered", {}))
    steps: list[float] = []
    t0 = time.perf_counter()
    p = finish(e, s, answered, patient)
    steps.append(_ms(t0))
    for _ in range(MAX_FILL):
        new = {k: c["truth"][k] for k in p.missing if k not in answered}
        if not new:
            break
        answered.update(new)
        t0 = time.perf_counter()
        p = finish(e, s, answered, patient)
        steps.append(_ms(t0))
    return p, steps, answered


async def one(lib: Library, c: dict, shared: dict) -> dict:
    e = lib.lookup(c["pack"])
    patient = {**c.get("patient", {}), **shared.get(c.get("patient_from", ""), {})}
    finding, findings, history = c.get("finding", ""), c["findings"], c.get("history", "")
    sources = lib.sources(e.key)

    def make(d=findings):
        return lambda: settle_pack(e, d, history, finding=finding)

    def failed():                      # an error or a timeout: a failed settlement, as the routes cache it
        return Settlement(failed=True)
    k = PC.key(e.key, finding, findings, history)

    # (a) cold open
    PC.clear()
    t0 = time.perf_counter()
    s = await PC.start(k, make(), fallback=failed)
    p = finish(e, s, c.get("answered", {}), patient, sources)
    ms_a = _ms(t0)

    # (b) open 2 s after /match, the prewarm running
    PC.clear()
    PC.start(k, make(), prewarm=True, fallback=failed)
    await asyncio.sleep(OPEN_DELAY_S)
    t0 = time.perf_counter()
    sb = await PC.start(k, make(), fallback=failed)
    finish(e, sb, c.get("answered", {}), patient, sources)
    ms_b = _ms(t0)

    # (c) more dictation after /match: the prewarmed key no longer matches, so the open is a MISS
    PC.clear()
    pre = PC.start(k, make(), prewarm=True, fallback=failed)
    await asyncio.sleep(OPEN_DELAY_S)
    more = findings + MORE_DICTATION
    t0 = time.perf_counter()
    sc = await PC.start(PC.key(e.key, finding, more, history), make(more), fallback=failed)
    finish(e, sc, c.get("answered", {}), patient, sources)
    ms_c = _ms(t0)
    await asyncio.gather(pre, return_exceptions=True)

    degraded = s.failed or sb.failed or sc.failed
    settled = {x.input: x.value for x in p.settled}
    shared[c["name"]] = {x.fact: x.value for x in p.settled if x.fact}
    truth = c["truth"]
    answered = c.get("answered", {})
    model_settled = {x.input: (x.value, x.quote) for x in p.settled if x.input not in answered and x.quote}
    wrong_values = {k: (v, q, truth[k]) for k, (v, q) in model_settled.items() if not _same(e, k, v, truth[k])}
    final, steps, filled = _fill(e, s, c, patient)
    outcome = (p.trace or {}).get("outcome")
    final_outcome = (final.trace or {}).get("outcome")
    want = c["expect_final"]
    want_settled, may = c["expect_settled"], set(c.get("accept_missing", []))
    return {"name": c["name"], "pack": c["pack"], "two_lesion": c.get("two_lesion", False),
            "ms_a": ms_a, "ms_b": ms_b, "ms_c": ms_c, "ms_d": steps, "degraded": degraded,
            "degraded_a": s.failed, "degraded_b": sb.failed, "degraded_c": sc.failed,
            "outcome": outcome, "final_outcome": final_outcome, "expect_final": want,
            "expect_outcome": c["expect_outcome"], "state": p.state, "expect_state": c["expect_state"],
            "wrong_proposal": (outcome is not None and outcome != want) or final_outcome != want,
            "wrong_values": wrong_values, "missing": p.missing, "expect_missing": c["expect_missing"],
            "asks": len(p.missing), "filled": sorted(set(filled) - set(answered)),
            "unasked": [x for x in want_settled if x not in settled and x not in may],
            "asked_instead": [x for x in want_settled if x not in settled and x in may],
            "settled": [x.model_dump() for x in p.settled], "possible": p.possible}


async def main(out_dir: Path) -> int:
    lib = Library(json.loads(BUNDLE.read_text()))
    cases = json.loads(CASES.read_text())["cases"]
    if check(lib, cases):
        print("expectations disagree with the engine: fix the cases before any run")
        return 1
    rows, shared = [], {}
    for c in cases:                      # sequential: latency is part of the gate
        rows.append(await one(lib, c, shared))
    out = out_dir / f"preview_lab_{os.getpid()}.json"
    out.write_text(json.dumps(rows, indent=1))
    # every row counts (review I4): a degraded open is a slow one (a model or Jev timeout); a degraded (b) open counts
    # as over the bar whatever its time
    lat = {x: [r[f"ms_{x}"] for r in rows] for x in "abc"}
    lat["d"] = [m for r in rows for m in r["ms_d"]]
    gate_b = [max(r["ms_b"], GATE_B_MS) if r["degraded_b"] else r["ms_b"] for r in rows]
    wrong_values = sum(len(r["wrong_values"]) for r in rows)
    wrong_proposals = sum(r["wrong_proposal"] for r in rows)
    b95, a95 = _pct(gate_b, 0.95), _pct(lat["a"], 0.95)
    passed = wrong_values == 0 and wrong_proposals == 0 and b95 < GATE_B_MS
    print(f"{len(rows)} cases -> {out}")
    print(f"GATE: {'PASS' if passed else 'FAIL'}  wrong values {wrong_values}  wrong proposals {wrong_proposals}  "
          f"(b) p95 {b95} ms, degraded (b) counted over the bar (gate < {GATE_B_MS})"
          + ("  [cold open slow: flagged for Hassan]" if passed and a95 >= GATE_B_MS else ""))
    for x, name in (("a", "cold open (MISS)"), ("b", "open 2 s after /match"), ("c", "open after more dictation"),
                    ("d", "answer path")):
        print(f"  ({x}) {name}, all rows: p50 {_pct(lat[x], 0.5)} p95 {_pct(lat[x], 0.95)} ms  n={len(lat[x])}")
    for x in "abc":
        bad = [r[f"ms_{x}"] for r in rows if r[f"degraded_{x}"]]
        good = [r[f"ms_{x}"] for r in rows if not r[f"degraded_{x}"]]
        print(f"  ({x}) degraded: n={len(bad)} p50 {_pct(bad, 0.5)} p95 {_pct(bad, 0.95)} ms; "
              f"not degraded: n={len(good)} p50 {_pct(good, 0.5)} p95 {_pct(good, 0.95)} ms")
    print(f"degraded: {sum(r['degraded'] for r in rows)}  unasked: {sum(bool(r['unasked']) for r in rows)}  "
          f"asked instead: {sum(len(r['asked_instead']) for r in rows)}")
    asks = [r["asks"] for r in rows]
    print(f"asks per card: mean {statistics.mean(asks):.2f} median {statistics.median(asks)} "
          f"<=2: {sum(a <= 2 for a in asks)}/{len(asks)}  distribution {sorted(Counter(asks).items())}")
    for pack in sorted({r["pack"] for r in rows}):
        xs = [r["asks"] for r in rows if r["pack"] == pack]
        print(f"  {pack}: asks mean {statistics.mean(xs):.2f} {sorted(xs)}  "
              f"(a) ms {sorted(int(r['ms_a']) for r in rows if r['pack'] == pack)}")
    for r in rows:
        if r["wrong_proposal"] or r["wrong_values"] or r["unasked"] or r["degraded"]:
            print(f"- {r['pack']} / {r['name']}: outcome {r['outcome']} final {r['final_outcome']} "
                  f"(want {r['expect_final']}), wrong values {r['wrong_values']}, unasked {r['unasked']}, "
                  f"degraded {r['degraded']}")
    return 0 if passed else 2


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check(Library(json.loads(BUNDLE.read_text())), json.loads(CASES.read_text())["cases"]))
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
