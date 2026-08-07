"""Evaluate the tier-2 semantic dictation checks against real cases.

Unit tests cover the plumbing (hallucinated spans dropped, failures
non-blocking). This exercises the PROMPT against the real model, which is the
part unit tests cannot reach.

The false-positive cases matter more than the true-positive ones: a checker
that cries wolf on clean dictation gets ignored, and an ignored checker is
worse than none. Clean cases are drawn from real reports that scored well.

Run:  poetry run python scripts/semantic_eval.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Load .env before importing anything that reads config at import time.
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

from rapid_reports_ai.dictation_integrity import check_dictation  # noqa: E402
from rapid_reports_ai.dictation_semantic import check_semantic  # noqa: E402

cases = json.loads((ROOT / "test_cases" / "semantic_eval.json").read_text())

tp = fp = fn = tn = 0
rows = []

for c in cases:
    tier1 = check_dictation(c["findings"])
    # Mirror the endpoint: tier 2 only runs when tier 1 is clean.
    flags = [] if tier1 else check_semantic(
        c["scan_type"], c["clinical_history"], c["findings"]
    )
    got = "flag" if flags else "clean"
    want = c["expect"]
    ok = got == want
    if want == "flag" and got == "flag":
        tp += 1
    elif want == "clean" and got == "flag":
        fp += 1
    elif want == "flag" and got == "clean":
        fn += 1
    else:
        tn += 1

    detail = "; ".join(f"{f.kind}:{c['findings'][f.start:f.end][:40]!r}" for f in flags)
    rows.append((("PASS" if ok else "FAIL"), c["name"], want, got,
                 ("tier1" if tier1 else "tier2"), detail))

w = max(len(r[1]) for r in rows)
print(f"{'':4}  {'case':{w}}  {'want':5}  {'got':5}  {'by':5}  detail")
for r in rows:
    print(f"{r[0]:4}  {r[1]:{w}}  {r[2]:5}  {r[3]:5}  {r[4]:5}  {r[5][:90]}")

print()
print(f"true positives : {tp}")
print(f"false positives: {fp}   <-- the number that decides whether this is usable")
print(f"false negatives: {fn}")
print(f"true negatives : {tn}")
sys.exit(0 if fp == 0 else 1)
