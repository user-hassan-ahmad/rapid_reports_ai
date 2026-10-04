"""Second round of live-evaluation fixes (2026-10-04). Synthetic cases only, no live model calls.
1. one card per clause: a negatives number check and an accuracy-lane item on the same clause become one item;
2. recommendation sentences are never asked the W1n / C1n support and certainty questions."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, jev_pass, negatives
from rapid_reports_ai.review_engine.items import ReviewItem, Span

from tests.review_engine_fakes import inp, jev, model
from tests.test_review_engine_engine import labels

RUN = "00000000-0000-0000-0000-0000000000f2"
RID = "00000000-0000-0000-0000-000000000001"
MINOR = adj.Judgement(cls="minor", kind="unsupported", label="Unsupported", reason="r", edit_mode="none")

REPORT = ("FINDINGS:\nA 3 cm pancreatic head mass. The common bile duct is not dilated at 6 mm. "
          "The portal vein is patent at 11 mm.\nIMPRESSION:\nPancreatic mass.")
DICT = "- 3 cm pancreatic head mass"


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"addressed": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(MINOR))
    monkeypatch.setattr(negatives, "_run_agent_with_model",
                        labels(["1 | default | - | yes", "2 | default | - | yes"]))


def _span(text: str, report: str = REPORT) -> Span:
    i = report.index(text)
    return Span(start=i, end=i + len(text), text=text)


def _neg(text: str, cls: str = "action", pointer: str = "6 mm") -> ReviewItem:
    return ReviewItem(key=f"n-{text}", report_id=RID, run_id=RUN, lane="accuracy", detectors=[negatives.DETECTOR],
                      kind="check", cls=cls, anchor=_span(text), label="Check: number",
                      evidence={"clause": text, "label": "default", "check_reason": "number", "pointer": pointer})


def _lane(text: str, cls: str = "action", detectors=("code.numbers",), evidence=None) -> ReviewItem:
    return ReviewItem(key=f"l-{text}", report_id=RID, run_id=RUN, lane="accuracy", detectors=list(detectors),
                      kind="unsupported", cls=cls, anchor=_span(text), label="Unsupported",
                      evidence=evidence if evidence is not None else {"numbers": ["6mm"]})


CBD = "The common bile duct is not dilated at 6 mm."
PV = "The portal vein is patent at 11 mm."


# ── 1. one card per clause ───────────────────────────────────────────────────

def test_tie_keeps_lane_item_with_merged_negatives_evidence():
    lane, neg = _lane(CBD), _neg(CBD)
    items, negs, merged = engine.one_card_per_clause([lane], [neg])
    assert items == [lane] and negs == []
    assert lane.detectors == ["code.numbers", negatives.DETECTOR]
    assert lane.evidence["check_reason"] == "number" and lane.evidence["pointer"] == "6 mm"
    assert lane.evidence["numbers"] == ["6mm"]                       # the lane's own evidence is kept
    assert merged == [{"kept": lane.id, "dropped": neg.id, "key": neg.key, "kind": neg.kind,
                       "anchor": neg.anchor.model_dump(), "merged": True}]


def test_higher_cls_wins_without_merging():
    lane, neg = _lane(CBD, cls="minor"), _neg(CBD, cls="action")
    items, negs, merged = engine.one_card_per_clause([lane], [neg])
    assert items == [] and negs == [neg] and neg.detectors == [negatives.DETECTOR]
    assert merged[0]["kept"] == neg.id and merged[0]["dropped"] == lane.id and merged[0]["merged"] is False

    lane, neg = _lane(CBD, cls="action"), _neg(CBD, cls="minor")
    items, negs, merged = engine.one_card_per_clause([lane], [neg])
    assert items == [lane] and negs == [] and "check_reason" not in lane.evidence
    assert lane.detectors == ["code.numbers"]


def test_lane_anchor_on_part_of_the_clause_still_counts_as_the_same_clause():
    lane = _lane("6 mm", detectors=("jev.supported",))
    items, negs, _ = engine.one_card_per_clause([lane], [_neg(CBD)])
    assert items == [lane] and negs == [] and lane.evidence["check_reason"] == "number"


def test_different_clauses_are_not_merged():
    lane, neg = _lane(PV), _neg(CBD)
    items, negs, merged = engine.one_card_per_clause([lane], [neg])
    assert items == [lane] and negs == [neg] and merged == []


def test_a_lane_anchor_bleeding_into_the_next_clause_is_not_that_clause():
    # the lane anchor covers the CBD clause plus the first word of the next one: only the CBD check pairs with it
    lane = _lane(CBD + " The")
    items, negs, _ = engine.one_card_per_clause([lane], [_neg(CBD), _neg(PV, pointer="11 mm")])
    assert items == [lane] and [n.anchor.text for n in negs] == [PV]


def test_only_number_checks_and_visible_accuracy_items_pair():
    other = _neg(CBD).model_copy(update={"evidence": {"check_reason": "uncertain", "pointer": "x"}})
    assumed = _neg(CBD).model_copy(update={"kind": "assumed_normal", "cls": "info", "evidence": {"label": "default"}})
    sup = _lane(CBD, cls="suppress")
    cov = _lane(CBD).model_copy(update={"lane": "coverage"})
    items, negs, merged = engine.one_card_per_clause([sup, cov], [other, assumed, _neg(CBD, cls="minor")])
    assert len(items) == 2 and len(negs) == 3 and merged == []


async def test_run_review_gives_one_card_for_an_invented_number_on_a_normal_clause():
    res = await engine.run_review(inp(REPORT, DICT), RUN)
    on_cbd = [i for i in res.items if i.anchor and i.cls != "suppress"
              and i.anchor.start < REPORT.index(CBD) + len(CBD) and REPORT.index(CBD) < i.anchor.end]
    assert len(on_cbd) == 1
    it = on_cbd[0]
    assert "code.numbers" in it.detectors and negatives.DETECTOR in it.detectors
    assert it.evidence["check_reason"] == "number" and it.evidence["pointer"] == "6 mm"
    assert any(d.get("merged") for d in res.run["deduped"])


async def test_run_review_keeps_both_when_negatives_failed(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("qwen down")
    monkeypatch.setattr(negatives, "_run_agent_with_model", boom)
    res = await engine.run_review(inp(REPORT, DICT), RUN)
    assert "negatives" in res.run["errors"]
    s, e = REPORT.index(CBD), REPORT.index(CBD) + len(CBD)
    on_cbd = [i for i in res.items if i.anchor and i.cls != "suppress" and i.anchor.start < e and s < i.anchor.end]
    # the code-built number check still comes out of a failed classifier; nothing is merged into the lane item
    assert sorted(tuple(i.detectors) for i in on_cbd) == [("code.numbers",), (negatives.DETECTOR,)]
    assert not any(d.get("merged") is not None for d in res.run["deduped"])


# ── 2. recommendations are never asked W1n / C1n ─────────────────────────────

@pytest.mark.parametrize("clause", [
    "MRI is recommended for further characterisation.",
    "Suggest follow-up CT in 3 months.",
    "Referral to the hepatobiliary team is advised.",
    "Correlate with tumour markers.",
])
def test_recommendation_is_not_positive(clause):
    assert jev_pass.recommendation(clause) and not jev_pass.positive(clause)


def test_negatives_candidates_use_the_shared_recommendation_helper():
    got = [c["clause"] for c in negatives.candidates(
        "FINDINGS:\nNo mass.\nIMPRESSION:\nNo acute abnormality. CT without contrast is recommended.")]
    assert "No mass." in got and not any("recommended" in c for c in got)
    assert not hasattr(negatives, "_RECOMMENDATION")          # one regex, in jev_pass


async def test_w1n_c1n_not_asked_of_recommendations(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"addressed": {"noul": 0.9}}, calls))
    report = ("FINDINGS:\nA 3 cm pancreatic head mass.\nIMPRESSION:\nPancreatic mass. "
              "MRI is recommended for further characterisation.")
    await jev_pass.run(inp(report, DICT), report)
    asked = [q["instructions"] for _, qs in calls for k, q in qs.items() if k.startswith(("sup", "cer"))]
    assert any("pancreatic head mass" in a for a in asked)
    assert not any("recommended" in a for a in asked)
