"""One card per claim across FINDINGS and IMPRESSION. Synthetic cases only, no live model calls.
A claim flagged in FINDINGS and repeated in IMPRESSION becomes ONE item: primary anchor in FINDINGS,
`evidence.also_anchors` listing the IMPRESSION copy, adjudicated (or classified) once. Matching is conservative."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import claims, engine, negatives
from rapid_reports_ai.review_engine.items import Candidate, Span

from tests.review_engine_fakes import inp, jev, model
from tests.test_review_engine_engine import labels

RUN = "00000000-0000-0000-0000-0000000000f3"
OVER = adj.Judgement(cls="minor", kind="overstated", label="Overstated", reason="r", edit_mode="none")


# ── matching (pure code) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b, negative", [
    ("There is a 3 cm mass in the pancreatic head consistent with adenocarcinoma.",
     "Pancreatic head mass consistent with adenocarcinoma.", False),
    ("Ill-defined hypoenhancing mass in the pancreatic head, in keeping with adenocarcinoma.",
     "Pancreatic head mass, likely adenocarcinoma.", False),
    ("Multiple liver lesions consistent with metastases.", "Liver metastases.", False),
    ("No lymphadenopathy.", "No peritoneal deposit or lymphadenopathy.", True),
    ("No ascites.", "No ascites", True),
])
def test_same_claim(a, b, negative):
    assert claims.same_claim(a, b, negative)
    assert claims.same_claim(b, a, negative)


@pytest.mark.parametrize("a, b, negative", [
    ("Segment 7 liver lesion consistent with metastasis.", "Segment 4 liver lesion consistent with metastasis.", False),
    ("Left adrenal nodule consistent with adenoma.", "Right adrenal nodule consistent with adenoma.", False),
    ("Liver lesion consistent with a cyst.", "Liver lesion consistent with metastasis.", False),
    ("No ascites.", "No lymphadenopathy.", True),
    ("Pancreatic head mass.", "Pancreatic duct dilatation.", False),
    ("Gallstones.", "Liver cyst.", False),
    ("Mass in the pancreatic head.", "Mass in the pancreatic head with liver metastases, ascites, peritoneal "
     "nodularity, splenic vein occlusion and varices.", False),   # a compound impression is not the same claim
])
def test_different_claims_never_match(a, b, negative):
    assert not claims.same_claim(a, b, negative)


def test_polarity_must_match():
    assert not claims.same_claim("Lymphadenopathy.", "No lymphadenopathy.", False)
    assert not claims.same_claim("No lymphadenopathy.", "Lymphadenopathy.", True)


def test_content_words_normalise_plurals_and_drop_hedges():
    assert claims.content_words("Liver metastases, likely.") == {"liver", "metastasis"}
    assert claims.content_words("No enlarged lymph nodes are seen.") == {"enlarged", "lymph", "node"}


def test_link_pairs_findings_to_impression_one_to_one_and_ambiguity_skipped():
    entries = [("findings", "No lymphadenopathy.", "k"), ("findings", "No peritoneal deposit.", "k"),
               ("impression", "No peritoneal deposit or lymphadenopathy.", "k")]
    assert claims.link_pairs(entries, negative=True) == []        # two findings partners: ambiguous, never merged
    entries = [("findings", "No lymphadenopathy.", "k"), ("impression", "No peritoneal deposit or lymphadenopathy.", "k"),
               ("impression", "No lymphadenopathy", "other-kind")]
    assert claims.link_pairs(entries, negative=True) == [(0, 1)]
    entries = [("findings", "Mass consistent with adenocarcinoma.", "k"),
               ("findings", "Pancreatic mass consistent with adenocarcinoma.", "k")]
    assert claims.link_pairs(entries, negative=False) == []        # same section: never linked


# ── lane candidates: grouped before adjudication ─────────────────────────────

REPORT = ("FINDINGS:\nThere is a 3 cm mass in the pancreatic head consistent with adenocarcinoma. The liver is "
          "normal. No lymphadenopathy.\nIMPRESSION:\nPancreatic head mass consistent with adenocarcinoma. "
          "No peritoneal deposit or lymphadenopathy.")
DICT = "- 3 cm pancreatic head mass, possibly adenocarcinoma"
F_MASS = "There is a 3 cm mass in the pancreatic head consistent with adenocarcinoma."
I_MASS = "Pancreatic head mass consistent with adenocarcinoma."


def _span(text, report=REPORT):
    i = report.index(text)
    return Span(start=i, end=i + len(text), text=text)


def _cand(text, kind="overstated", section="FINDINGS", lane="accuracy"):
    return Candidate(lane=lane, kind=kind, section=section, anchor=_span(text), detector="jev.certainty",
                     evidence={"score": 0.8, "clause": text})


def test_group_claims_puts_findings_first_and_records_the_impression_anchor():
    i_c, f_c = _cand(I_MASS, section="IMPRESSION"), _cand(F_MASS)
    groups, linked = engine.group_claims([i_c, f_c], REPORT, ["FINDINGS", "IMPRESSION"])
    assert len(groups) == 1 and groups[0][0] is f_c and linked == [True]


def test_group_claims_never_merges_different_kinds_or_findings():
    groups, _ = engine.group_claims([_cand(F_MASS), _cand(I_MASS, kind="unsupported", section="IMPRESSION")], REPORT,
                                 ["FINDINGS", "IMPRESSION"])
    assert len(groups) == 2
    other = "No peritoneal deposit or lymphadenopathy."
    groups, _ = engine.group_claims([_cand(F_MASS), _cand(other, section="IMPRESSION")], REPORT,
                                 ["FINDINGS", "IMPRESSION"])
    assert len(groups) == 2


def test_engine_one_item_one_verdict_for_a_certainty_claim_in_both_sections(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"addressed": {"noul": 0.9}, "cer*": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(OVER, calls))
    monkeypatch.setattr(negatives, "_run_agent_with_model",
                        labels(["1 | default | - | no", "2 | dictated | - | no", "3 | dictated | - | no"]))
    monkeypatch.setenv("RR_REVIEW_LANES", "accuracy")
    res = asyncio.run(engine.run_review(inp(REPORT, DICT), RUN))
    over = [it for it in res.items if it.kind == "overstated"]
    assert len(over) == 1
    it = over[0]
    assert it.anchor.text == F_MASS
    assert [a["text"] for a in it.evidence["also_anchors"]] == [I_MASS]
    a = it.evidence["also_anchors"][0]
    assert REPORT[a["start"]:a["end"]] == I_MASS
    judged = [kw["user_prompt"] for kw in calls if I_MASS in kw["user_prompt"] or F_MASS in kw["user_prompt"]]
    assert len(judged) == 1 and I_MASS in judged[0] and F_MASS in judged[0]   # one adjudication covers both


# ── negatives: one classifier verdict per claim ──────────────────────────────

def _route(lines, report=REPORT):
    i = inp(report, DICT)
    cands = [{**c, "number": False} for c in negatives.candidates(report)]
    labs = negatives.parse_labels(lines, len(cands))
    return cands, negatives.route(i, RUN, cands, labs)


def test_negatives_claim_in_findings_and_impression_is_one_item_with_the_worst_label():
    cands, (items, _, _) = _route(["1 | default | - | no", "2 | dictated | - | no", "3 | implicated | ascites | no"])
    assert [c["clause"] for c in cands] == ["The liver is normal.", "No lymphadenopathy.",
                                            "No peritoneal deposit or lymphadenopathy."]
    lymph = [it for it in items if "lymphadenopathy" in (it.anchor.text if it.anchor else "")]
    assert len(lymph) == 1
    it = lymph[0]
    assert it.anchor.text == "No lymphadenopathy"
    assert it.section == "FINDINGS"
    assert it.kind == "assumed_normal" and it.evidence["form"] == "negative"
    also = it.evidence["also_anchors"]
    assert len(also) == 1 and "peritoneal deposit or lymphadenopathy" in also[0]["text"]
    assert it.evidence["claim_labels"] == ["dictated", "implicated"]


def test_negatives_grouped_contradiction_is_a_check_never_a_pre_applied_removal():
    _, (items, doc, _) = _route(["1 | default | - | no", "2 | contradicted | node | no", "3 | default | - | no"])
    assert doc == REPORT                                             # nothing removed
    lymph = [it for it in items if it.evidence.get("also_anchors")]
    assert len(lymph) == 1 and lymph[0].kind == "check" and lymph[0].evidence["check_reason"] == "conflict"
    assert lymph[0].status == "open" and lymph[0].edit is None


def test_negatives_both_dictated_no_item():
    _, (items, _, _) = _route(["1 | default | - | no", "2 | dictated | - | no", "3 | dictated | - | no"])
    assert [it.evidence["clause"] for it in items] == ["The liver is normal."]


def test_negatives_unlinked_clauses_unchanged():
    report = "FINDINGS:\nNo ascites.\nIMPRESSION:\nNo lymphadenopathy."
    _, (items, _, _) = _route(["1 | implicated | x | no", "2 | default | - | no"], report)
    assert len(items) == 2 and not any((it.evidence or {}).get("also_anchors") for it in items)
