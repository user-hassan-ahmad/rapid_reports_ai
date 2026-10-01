"""Run the fixture set through the triage candidates, live, and print/save a summary.

Usage (from backend/, keys in .env):
    set -a; . ./.env; set +a
    .venv/bin/python -m rapid_reports_ai.scripts.triage_bakeoff [--only code|jev|qwen-lp] [--concurrency 4]

Candidates: code (lexicon), jev (the questions the dictation package asks per utterance) and
qwen-lp (Cerebras qwen-3.8 first-token logprobs, eval only). Calibration is printed per
question for jev and qwen-lp over the cases both answered. (The Groq Qwen hard-label
candidate was retired on 2026-09-29.)

Never run by pytest. Writes docs/model-migration/triage-bakeoff-<date>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from rapid_reports_ai.dictation_triage import TRIAGE_QUESTIONS, JevTriager, TriageState
from rapid_reports_ai.scripts.bakeoff_baselines import baseline_triage
from rapid_reports_ai.scripts.calibration_report import calibration_block, hard_choice
from rapid_reports_ai.scripts.qwen_logprob import QWEN_LP_LABEL, QwenLogprob
from rapid_reports_ai.scripts.triage_summary import Record, format_summary, summarise

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "triage_utterances.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]


def code_record(case: dict) -> Record:
    """The plain-code baseline as a candidate row. No confidence (a lexicon has none)."""
    t0 = time.perf_counter()
    action = baseline_triage(case["committed"], case["active"], case["utterance"])
    return Record(
        id=case["id"], candidate="code", expected_action=case["expected_action"], action=action,
        confidence=None, latency_ms=int((time.perf_counter() - t0) * 1000), cost_usd=None, hard=case["hard"],
        error=None, is_correction=1.0 if action == "correct_previous_finding" else 0.0,
        expected_is_correction=case["expected_is_correction"], needs_committed_edit=None,
        expected_needs_committed_edit=case["expected_needs_committed_edit"],
    )


CALIBRATED = ("jev", "qwen-lp")


def triage_calibration(records: list[Record]) -> list[tuple[dict, str]]:
    """Per question, over the cases every calibrated candidate answered. Hard labels
    (qwen) enter as certainty; code states no probability and is left out."""
    by: dict[str, dict[str, Record]] = {}
    for r in records:
        if r.candidate in CALIBRATED:
            by.setdefault(r.id, {})[r.candidate] = r
    cases = [c for c in by.values() if all(k in c and c[k].error is None for k in CALIBRATED)]
    present = [k for k in CALIBRATED if any(k in c for c in by.values())]
    out = []

    def dist(r: Record) -> dict[str, float]:
        return r.probabilities if r.probabilities else hard_choice(r.action)

    out.append(calibration_block("action", "choice", {
        k: ([dist(c[k]) for c in cases], [c[k].expected_action for c in cases]) for k in present
    }))
    for q, exp in (("is_correction", "expected_is_correction"),
                   ("needs_committed_edit", "expected_needs_committed_edit")):
        rows = [c for c in cases if getattr(c["jev"], exp) is not None]

        def val(r: Record, q: str = q) -> float:
            v = getattr(r, q)
            return v

        out.append(calibration_block(q, "noul", {
            k: ([val(c[k]) for c in rows], [int(getattr(c[k], exp)) for c in rows]) for k in present
        }))
    return out


_QWEN_LP: QwenLogprob | None = None


async def qwen_lp_record(case: dict, state: TriageState) -> Record:
    global _QWEN_LP
    if _QWEN_LP is None:
        _QWEN_LP = QwenLogprob()
    a = await _QWEN_LP.answer(state.as_payload(), TRIAGE_QUESTIONS)
    return Record(
        id=case["id"], candidate="qwen-lp", expected_action=case["expected_action"], action=a["action"]["choice"],
        confidence=a["action"]["confidence"], latency_ms=a["latency_ms"], cost_usd=None, hard=case["hard"],
        error=None, is_correction=a["is_correction"]["noul"], expected_is_correction=case["expected_is_correction"],
        needs_committed_edit=a["needs_committed_edit"]["noul"],
        expected_needs_committed_edit=case["expected_needs_committed_edit"],
        probabilities=a["action"]["probabilities"],
    )


async def run_case(case: dict, candidates: list[str], sem: asyncio.Semaphore) -> list[Record]:
    state = TriageState(case["committed"], case["active"], case["utterance"], case.get("scan_type", ""))
    out: list[Record] = []
    async with sem:
        for cand in candidates:  # sequential per case so the two latencies are not contended
            if cand == "code":
                out.append(code_record(case))
                continue
            try:
                if cand == "qwen-lp":
                    out.append(await qwen_lp_record(case, state))
                    continue
                d = await JevTriager().classify(state)
                out.append(Record(
                    id=case["id"], candidate=cand, expected_action=case["expected_action"], action=d.action,
                    confidence=d.confidence, latency_ms=d.latency_ms, cost_usd=d.cost_usd, hard=case["hard"],
                    error=None, is_correction=d.is_correction, expected_is_correction=case["expected_is_correction"],
                    needs_committed_edit=d.needs_committed_edit,
                    expected_needs_committed_edit=case["expected_needs_committed_edit"],
                    probabilities=d.probabilities,
                ))
            except Exception as e:
                out.append(Record(
                    id=case["id"], candidate=cand, expected_action=case["expected_action"], action=None,
                    confidence=None, latency_ms=0, cost_usd=None, hard=case["hard"], error=type(e).__name__,
                    is_correction=None, expected_is_correction=None, needs_committed_edit=None,
                    expected_needs_committed_edit=None,
                ))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["code", "jev", "qwen-lp"])
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    candidates = [args.only] if args.only else ["code", "jev", "qwen-lp"]
    needed = {"jev": "OPENROUTER_API_KEY", "qwen-lp": "CEREBRAS_API_KEY"}
    missing = [needed[c] for c in candidates if c in needed and not os.environ.get(needed[c])]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2
    cases = load_cases()
    sem = asyncio.Semaphore(args.concurrency)
    nested = await asyncio.gather(*(run_case(c, candidates, sem) for c in cases))
    records = [r for rs in nested for r in rs]

    summary = summarise(records)
    print(format_summary(summary))
    blocks = triage_calibration(records) if len(candidates) > 1 else []
    calibration = [s for s, _ in blocks]
    if blocks:
        print(f"\n== calibration (qwen = shipped Groq qwen3.6, hard labels; {QWEN_LP_LABEL})")
        for _, text in blocks:
            print(text)
    wrong = [r for r in records if r.error is None and r.action != r.expected_action]
    if wrong:
        print("\n-- disagreements --")
        for r in wrong:
            print(f"   {r.candidate:<4} {r.id:<14} expected={r.expected_action:<26} got={r.action} conf={r.confidence}")
    errors = [r for r in records if r.error]
    if errors:
        print("\n-- errors --")
        for r in errors:
            print(f"   {r.candidate:<4} {r.id:<14} {r.error}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"triage-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": summary, "calibration": calibration, "records": [r.__dict__ for r in records]}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
