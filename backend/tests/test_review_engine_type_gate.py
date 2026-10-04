"""Jev statement-type gate (TB wording, type_tier lab): one `typ{i}` choice per checked clause on the existing
report-only request. The accuracy lane keeps W1n / C1n answers only for abnormal / mixed clauses; normal clauses are
negatives-classifier candidates; a mixed clause's negative tail goes to the classifier when code can split and locate
it (else the whole clause is routed as abnormal); not_a_finding gives nothing. On request failure: today's lexicon.
Synthetic cases only, no live model calls."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, jev_pass, negatives
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.checks import run_checks
from rapid_reports_ai.review_engine.lanes import LaneContext
from rapid_reports_ai.review_engine.lanes.accuracy import AccuracyLane

from tests.review_engine_fakes import inp, jev, model
from tests.test_review_engine_engine import labels


def typ(choice):
    return {"type": "choice", "choice": choice, "probabilities": {c: (1.0 if c == choice else 0.0)
                                                                  for c in jev_pass.TYPES}}


# ── code split of a mixed clause's negative / normal tail ────────────────────

@pytest.mark.parametrize("clause, head, tails", [
    ("The spleen is enlarged at 15 cm, with no focal lesion.", "The spleen is enlarged at 15 cm", ["No focal lesion"]),
    ("Ulnar styloid remodelling without fracture.", "Ulnar styloid remodelling", ["No fracture"]),
    ("Partial thickness tear of the supraspinatus tendon; the remaining rotator cuff tendons are intact.",
     "Partial thickness tear of the supraspinatus tendon", ["the remaining rotator cuff tendons are intact"]),
    ("The mass abuts the vein without contour deformity; the artery fat plane is preserved.",
     "The mass abuts the vein", ["No contour deformity", "the artery fat plane is preserved"]),
    ("A small left pleural effusion; no pneumothorax.", "A small left pleural effusion", ["No pneumothorax"]),
])
def test_split_tails(clause, head, tails):
    assert jev_pass.split_tails(clause) == (head, tails)


@pytest.mark.parametrize("clause", [
    "No ascites.",
    "Severe left hydronephrosis.",
    "The mass shows no enhancement but invades the duodenum.",          # a positive turn after the negative
    "The liver is normal in size, with no focal lesion.",                # the head is itself normal
    "The liver is normal apart from a 9 mm cyst.",
    "The cyst has no septation and is enlarging.",
])
def test_no_split(clause):
    assert jev_pass.split_tails(clause) is None


# ── the shared pass ──────────────────────────────────────────────────────────

REPORT = ("FINDINGS:\nThe liver is normal. A 14 mm left renal cyst. The spleen is enlarged at 15 cm, with no focal "
          "lesion. The kidneys enhance symmetrically.\nIMPRESSION:\nLeft renal cyst. MRI is recommended.")
DICT = "- 14 mm left renal cyst\n- Spleen 15 cm"
CLS = ["The liver is normal.", "A 14 mm left renal cyst.", "The spleen is enlarged at 15 cm, with no focal lesion.",
       "The kidneys enhance symmetrically.", "Left renal cyst.", "MRI is recommended."]
TYPES = {"typ0": typ("normal"), "typ1": typ("abnormal"), "typ2": typ("mixed"), "typ3": typ("normal"),
         "typ4": typ("abnormal"), "typ5": typ("not_a_finding")}


async def test_typ_on_the_report_request_and_loose_support_questions(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(TYPES, calls))
    jp = await jev_pass.run(inp(REPORT, DICT), REPORT)
    assert jp.clauses == CLS
    report_qs = next(qs for s, qs in calls if s.startswith("REPORT:"))
    assert {f"typ{i}" for i in range(6)} <= set(report_qs)
    assert report_qs["typ2"]["type"] == "choice" and set(report_qs["typ2"]["criteria"]) == set(jev_pass.TYPES)
    assert '"The spleen is enlarged at 15 cm, with no focal lesion."' in report_qs["typ2"]["instructions"]
    support = next(qs for s, qs in calls if "CLINICAL HISTORY:" in s)
    # asked of every clause that is not a recommendation or a plain negative (the type gate decides afterwards)
    assert {"sup0", "sup1", "sup2", "sup3", "sup4"} <= set(support) and "sup5" not in support
    assert '"The spleen is enlarged at 15 cm"' in support["cer2"]["instructions"]       # the split head
    assert len(calls) == 3                                                             # no extra round trip
    assert [jp.clause_type(i) for i in range(6)] == ["normal", "abnormal", "mixed", "normal", "abnormal",
                                                       "not_a_finding"]
    assert jp.types["The kidneys enhance symmetrically."] == "normal"


async def test_type_fallback_is_todays_lexicon(monkeypatch):
    async def fake(state, qs):
        if state.startswith("REPORT:"):
            raise RuntimeError("down")
        return await jev()(state, qs)
    monkeypatch.setattr(rc, "_jev", fake)
    jp = await jev_pass.run(inp(REPORT, DICT), REPORT)
    assert jp.omit_error and jp.types == {}
    assert [jp.keeps(i) for i in range(6)] == [jev_pass.positive(t) for t in CLS]


async def test_unparseable_type_answer_falls_back_per_clause(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({**TYPES, "typ0": {"noul": 0.4}}))
    jp = await jev_pass.run(inp(REPORT, DICT), REPORT)
    assert jp.clause_type(0) is None and jp.keeps(0) is False and jp.keeps(1) is True


# ── the accuracy lane ────────────────────────────────────────────────────────

async def _lane(monkeypatch, over):
    monkeypatch.setattr(rc, "_jev", jev({**TYPES, "cer*": {"noul": 0.9}, **over}))
    i = inp(REPORT, DICT)
    a = i.artifacts
    al = align(a.report, a.dictated_findings, "", a.sections)
    jp = await jev_pass.run(i, a.report)
    ctx = LaneContext(alignment=al, jev=jp, checks=run_checks(a.report, a.dictated_findings, "", i.scan_type, al))
    return [c for c in await AccuracyLane().candidates(i, ctx) if c.detector == "jev.certainty"]


async def test_lane_keeps_answers_only_for_abnormal_and_mixed(monkeypatch):
    got = await _lane(monkeypatch, {})
    texts = sorted(c.anchor.text for c in got)
    assert texts == sorted(["A 14 mm left renal cyst.", "The spleen is enlarged at 15 cm", "Left renal cyst."])
    spleen = next(c for c in got if c.anchor.text.startswith("The spleen"))
    assert REPORT[spleen.anchor.start:spleen.anchor.end] == "The spleen is enlarged at 15 cm"
    assert spleen.evidence["clause"] == "The spleen is enlarged at 15 cm"


async def test_lane_mixed_without_a_split_is_the_whole_clause(monkeypatch):
    got = await _lane(monkeypatch, {"typ3": typ("mixed")})            # "The kidneys enhance symmetrically."
    assert "The kidneys enhance symmetrically." in [c.anchor.text for c in got]


# ── negatives candidates follow the type ─────────────────────────────────────

def test_negatives_candidates_by_type():
    types = {c: jev_pass.clause_type_of(TYPES[f"typ{i}"]) for i, c in enumerate(CLS)}
    got = [c["clause"] for c in negatives.candidates(REPORT, types)]
    assert got == ["The liver is normal.", "No focal lesion", "The kidneys enhance symmetrically."]
    assert negatives.candidates(REPORT) == negatives.candidates(REPORT, None)     # no types: today's lexicon
    assert "The kidneys enhance symmetrically." not in [c["clause"] for c in negatives.candidates(REPORT)]
    spans = negatives.candidate_spans(REPORT, types)
    assert [REPORT[s:e] for s, e in spans] == ["The liver is normal", "focal lesion",
                                                "The kidneys enhance symmetrically"]


def test_a_mixed_tail_code_cannot_locate_routes_nothing_to_negatives():
    report = "FINDINGS:\nA small effusion; no pneumothorax.\nIMPRESSION:\nEffusion."
    types = {"A small effusion; no pneumothorax.": "mixed", "Effusion.": "abnormal"}
    assert [c["clause"] for c in negatives.candidates(report, types)] == ["No pneumothorax"]
    report2 = "FINDINGS:\nThe kidneys show scarring, which is unchanged.\nIMPRESSION:\nScarring."
    assert negatives.candidates(report2, {"The kidneys show scarring, which is unchanged.": "mixed"}) == []


def test_pure_negatives_stay_candidates_whatever_the_type():
    report = "FINDINGS:\nNo ascites.\nIMPRESSION:\nNormal."
    assert [c["clause"] for c in negatives.candidates(report, {"No ascites.": "abnormal"})][0] == "No ascites."


async def test_engine_feeds_types_to_the_negatives_classifier(monkeypatch):
    seen = []

    def lab(kw):
        seen.append(kw["user_prompt"])
        return ["1 | default | - | no"]
    monkeypatch.setattr(rc, "_jev", jev(TYPES))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(cls="minor", kind="overstated", label="x",
                                                                           reason="r", edit_mode="none")))
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(lab))
    monkeypatch.setenv("RR_REVIEW_LANES", "accuracy")
    await engine.run_review(inp(REPORT, DICT), "run-t")
    listing = seen[0].split("STATEMENTS TO CLASSIFY:")[1]
    assert "The kidneys enhance symmetrically." in listing and "No focal lesion" in listing
    assert "The spleen is enlarged" not in listing
