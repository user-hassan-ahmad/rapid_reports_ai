"""Post-generation check (spec 2026-09-30-post-generation-check-design): Jev flags, focal Qwen repair."""
from __future__ import annotations

import asyncio

import pytest

from rapid_reports_ai import quick_report_quality as qq

REPORT = """COMPARISON:
None.

TECHNIQUE:
CT abdomen and pelvis with intravenous contrast.

FINDINGS:
A 3 cm hypodense mass in the pancreatic head compresses the distal common bile duct. No superior mesenteric vein encasement, portal vein encasement, or hepatic deposit. No pericolic or paracolic fluid collection.

The spleen is normal in size.

IMPRESSION:
Pancreatic head mass causing biliary obstruction. Urgent hepatobiliary referral recommended.

Dr A Radiologist"""


def test_sections_and_clauses():
    fnd, imp = qq.report_sections(REPORT)
    assert fnd.startswith("A 3 cm hypodense mass") and fnd.endswith("The spleen is normal in size.")
    assert imp.startswith("Pancreatic head mass") and "Dr A" not in imp
    assert qq.clauses(fnd) == [
        "A 3 cm hypodense mass in the pancreatic head compresses the distal common bile duct.",
        "No superior mesenteric vein encasement",
        "No portal vein encasement",
        "No hepatic deposit",
        "No pericolic or paracolic fluid collection.",     # a bare "or" never splits
        "The spleen is normal in size.",
    ]


def test_positive_items_drop_negatives_and_background():
    findings = ("- 3 cm pancreatic head mass\n- CBD dilated to 12 mm\n- No ascites\n"
                "- Liver, spleen, kidneys unremarkable\n- Lung bases clear\n- Nil else")
    assert qq.positive_items(findings) == ["3 cm pancreatic head mass", "CBD dilated to 12 mm"]


FINDINGS = "- 3 cm hypodense mass at the head of the pancreas\n- CBD dilated to 12 mm\n- Intrahepatic duct dilatation\n- No ascites"
OPTIONS = [{"id": "fn0", "kind": "finding_negative", "sentence": "No intrahepatic biliary duct dilatation."},
           {"id": "fn1", "kind": "finding_negative", "sentence": "No splenic vein thrombus."}]


def _stub_jev(monkeypatch, contra: dict, reported: dict):
    """contra: clause/option text -> score; reported: dictated item -> score. Default 0.05 / 0.95."""
    calls = []
    async def fake(state, questions):
        calls.append((state, questions))
        out = {}
        for k, q in questions.items():
            t = q["instructions"]
            if t.startswith(qq.Q_CONTRA):
                out[k] = {"noul": contra.get(t[len(qq.Q_CONTRA):], 0.05)}
            else:
                out[k] = {"noul": reported.get(t[len(qq.Q_OMIT):], 0.95)}
        return out
    monkeypatch.setattr(qq.qb, "_jev", fake)
    return calls


@pytest.mark.asyncio
async def test_check_asks_two_parallel_calls_and_flags(monkeypatch):
    calls = _stub_jev(monkeypatch, {"No portal vein encasement": 0.8, "No intrahepatic biliary duct dilatation.": 0.86},
                      {"CBD dilated to 12 mm": 0.2})
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    states = sorted(c[0].split("\n")[0] for c in calls)
    assert states == ["REPORT:", "SCAN TYPE: CT AP"]
    contra_qs = [q["instructions"] for s, qs in calls if s.startswith("SCAN") for q in qs.values()]
    assert qq.Q_CONTRA + "No hepatic deposit" in contra_qs and qq.Q_CONTRA + "No splenic vein thrombus." in contra_qs
    omit_qs = [q["instructions"] for s, qs in calls if s.startswith("REPORT") for q in qs.values()]
    assert omit_qs == [qq.Q_OMIT + t for t in ("3 cm hypodense mass at the head of the pancreas", "CBD dilated to 12 mm",
                                               "Intrahepatic duct dilatation")]
    assert [(f.kind, f.text) for f in res.flags] == [("contradiction", "No portal vein encasement"),
                                                     ("omission", "CBD dilated to 12 mm")]
    assert res.bad_option_ids == ["fn0"]
    assert res.error is None


@pytest.mark.asyncio
async def test_check_failure_returns_no_flags_and_the_reason(monkeypatch):
    async def boom(state, questions):
        raise RuntimeError("jev down")
    monkeypatch.setattr(qq.qb, "_jev", boom)
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert res.flags == [] and res.bad_option_ids == [] and "jev down" in res.error
