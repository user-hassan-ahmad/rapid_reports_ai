"""Byte-identity pins for the quick path while its engine moves to shared modules
(spec 2026-09-30-template-pipeline-mirror-design §1). Regenerate only on an intended change:
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_quick_pipeline.py"""
from __future__ import annotations

import json
import os
import pathlib

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_quality as qq

from tests.test_quick_report_brief import JEV, QWEN, SHEET, _stub

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden_quick.json"
FINDINGS = "8 mm right subdural haematoma. 3 mm midline shift."
REPORT = """FINDINGS:
An 8 mm right subdural haematoma. No skull fracture. No hydrocephalus, no herniation, and no intraventricular extension.

IMPRESSION:
Acute right subdural haematoma with 3 mm midline shift.

Dr A"""
LIST_REPORT = "FINDINGS:\nNo ascites, collection or free air.\n\nIMPRESSION:\nNormal."


async def _snapshot(monkeypatch) -> dict:
    _stub(monkeypatch, JEV, QWEN)
    brief = await qb.compile_brief(SHEET, "CT head", FINDINGS, "fall")

    async def fake_jev(state, qs):
        return {k: {"noul": 0.9 if k in ("c1", "r1") else 0.1} for k in qs}
    target = qq.rc if hasattr(qq, "rc") else qq.qb
    monkeypatch.setattr(target, "_jev", fake_jev)
    res = await qq.check(REPORT, FINDINGS, "CT head", [])
    fnd, imp = qq.report_sections(REPORT)
    return {"brief_text": brief.text, "decisions": brief.decisions,
            "clauses": qq.clauses(fnd) + qq.clauses(imp),
            "check": res.model_dump(),
            "removed_sentence": qq.remove_negative_clause(REPORT, "No skull fracture"),
            "removed_list": qq.remove_negative_clause(LIST_REPORT, "No ascites")}


async def test_quick_pipeline_matches_golden(monkeypatch):
    snap = json.loads(json.dumps(await _snapshot(monkeypatch)))
    assert snap["removed_sentence"] != REPORT, "sentence removal was a no-op"
    assert snap["removed_list"] != LIST_REPORT, "list-item removal was a no-op"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=1, sort_keys=True))
    assert snap == json.loads(GOLDEN.read_text())
