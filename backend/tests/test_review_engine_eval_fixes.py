"""Fixes from the 20-report live evaluation (2026-10-04). Synthetic cases only, no live model calls.
1. invented measurements are never minor; 2. normal statements in any wording are the negatives classifier's;
3. every negatives check states its reason; 4. a brief option's own sentence grounds its insert;
5. negatives-owned lane candidates are held back from adjudication while the classifier runs."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, jev_pass, negatives, verifier
from rapid_reports_ai.review_engine.items import Candidate, Span

from tests.review_engine_fakes import inp, jev, model
from tests.test_review_engine_engine import _all_default, labels

RUN = "00000000-0000-0000-0000-0000000000f1"
MINOR = adj.Judgement(cls="minor", kind="unsupported", label="Unsupported", reason="r", edit_mode="none")


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"addressed": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(MINOR))
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(_all_default))


# ── 1. invented measurements: at least action ───────────────────────────────

NUM_REPORT = "FINDINGS:\nA 3 cm pancreatic head mass. The common bile duct measures 6 mm.\nIMPRESSION:\nPancreatic mass."
NUM_DICT = "- 3 cm pancreatic head mass"


def _cbd(report=NUM_REPORT):
    i = report.index("The common bile duct")
    return Span(start=i, end=i + len("The common bile duct measures 6 mm."), text="The common bile duct measures 6 mm.")


async def test_code_numbers_flag_judged_minor_becomes_action():
    i_ = inp(NUM_REPORT, NUM_DICT)
    c = Candidate(lane="accuracy", kind="unsupported", anchor=_cbd(), evidence={"numbers": ["6mm"]},
                  detector="code.numbers")
    it = engine.build_item(i_, RUN, adj.Outcome(group=[c], judgement=MINOR))
    assert it.cls == "action" and it.evidence["invented_numbers"] == ["6mm"]
    assert it.evidence["cls_floor"] == {"from": "minor", "to": "action"}


async def test_w1n_unsupported_with_undictated_measurement_becomes_action():
    i_ = inp(NUM_REPORT, NUM_DICT)
    c = Candidate(lane="accuracy", kind="unsupported", anchor=_cbd(),
                  evidence={"score": 0.1, "clause": "The common bile duct measures 6 mm."}, detector="jev.supported")
    info = MINOR.model_copy(update={"cls": "info"})
    assert engine.build_item(i_, RUN, adj.Outcome(group=[c], judgement=info)).cls == "action"
    # adjudicator failure (minor, no fix) is floored too
    assert engine.build_item(i_, RUN, adj.Outcome(group=[c], judgement=adj.fallback([c]), error="x")).cls == "action"


async def test_floor_respects_suppress_dictated_numbers_and_bare_counts():
    i_ = inp(NUM_REPORT, NUM_DICT + "\n- CBD 6 mm")
    c = Candidate(lane="accuracy", kind="unsupported", anchor=_cbd(),
                  evidence={"clause": "The common bile duct measures 6 mm."}, detector="jev.supported")
    assert engine.build_item(i_, RUN, adj.Outcome(group=[c], judgement=MINOR)).cls == "minor"   # dictated: no floor
    sup = MINOR.model_copy(update={"cls": "suppress"})
    c2 = c.model_copy(update={"detector": "code.numbers", "evidence": {"numbers": ["6mm"]}})
    assert engine.build_item(inp(NUM_REPORT, NUM_DICT), RUN, adj.Outcome(group=[c2], judgement=sup)).cls == "suppress"
    c3 = c.model_copy(update={"detector": "code.numbers", "evidence": {"numbers": ["3"]}})          # a count
    assert engine.build_item(inp(NUM_REPORT, NUM_DICT), RUN, adj.Outcome(group=[c3], judgement=MINOR)).cls == "minor"


async def test_run_review_floors_invented_cbd_measurement():
    res = await engine.run_review(inp(NUM_REPORT, NUM_DICT), RUN)
    it = next(i for i in res.items if "code.numbers" in i.detectors)
    assert it.cls == "action"


async def test_negatives_number_check_with_measurement_is_action(monkeypatch):
    report = ("FINDINGS:\nA 3 cm pancreatic head mass. The common bile duct is not dilated at 6 mm.\n"
              "IMPRESSION:\nPancreatic mass.")
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(["1 | default | - | yes"]))
    items, _ = await negatives.classify_negatives(inp(report, NUM_DICT), RUN)
    assert [(i.kind, i.cls, i.evidence["check_reason"], i.evidence["pointer"]) for i in items] == \
        [("check", "action", "number", "6 mm")]


async def test_negatives_number_check_without_unit_stays_minor(monkeypatch):
    report = "FINDINGS:\nA 3 cm pancreatic head mass. No liver lesions in segments 2 and 5 of 8.\nIMPRESSION:\nMass."
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(["1 | default | - | yes"]))
    items, _ = await negatives.classify_negatives(inp(report, NUM_DICT), RUN)
    assert [(i.kind, i.cls, i.evidence["check_reason"]) for i in items] == [("check", "minor", "number")]


# ── 2. normal statements in any wording ─────────────────────────────────────

@pytest.mark.parametrize("clause", [
    "The scapholunate ligament maintains continuity.",          # maintains continuity
    "The anterior cruciate ligament is intact.",                # copula + intact
    "Cruciate ligaments intact.",                               # bare clause-final predicate
    "Disc heights are preserved.",                              # preserved
    "Joint spaces are maintained.",                             # maintained
    "The liver surface is smooth.",                             # is smooth
    "The portal vein is patent.",                               # patent
    "The lungs are clear, with no effusion.",                   # clear + trailing "with no" aside
    "The marrow signal is within normal limits.",               # within normal limits
    "The ventricles are normal in size and configuration.",     # normal in size/configuration
    "The aorta is normal in calibre.",                          # normal in calibre
    "The cortex appears intact throughout.",                    # appears + qualifier
    "No focal abnormality is seen.",                            # no abnormality
    "The retroperitoneum shows no lymphadenopathy.",            # subject shows no ...
    "The hemispheres, basal ganglia and brainstem show no acute change or haemorrhage.",   # listed subject
    "The aorta and its branches are patent without aneurysm or dissection.",              # patent without ...
    "The fibrocartilage complex maintains continuity without detachment.",                # continuity without ...
    "The intrahepatic bile ducts are not dilated.",             # is not <predicate>
    "The gallbladder is not distended and the biliary tree is not dilated.",              # two such parts
])
def test_normal_statement_is_not_positive_and_is_a_negatives_candidate(clause):
    assert jev_pass.normal_statement(clause) and not jev_pass.positive(clause)
    report = f"FINDINGS:\n{clause}\nIMPRESSION:\nNo acute abnormality."
    assert clause in [c["clause"] for c in negatives.candidates(report)]


@pytest.mark.parametrize("clause", [
    "The common bile duct measures 6 mm and is smooth.",        # a number: never a plain normal
    "The wall is smooth and thickened.",                        # predicate does not close the clause
    "A smooth-walled cyst arises from the kidney.",             # compound adjective
    "The mass abuts the vein with preserved fat plane.",        # mid-clause descriptor
    "The ligament is intact but thickened.",
    "The mass shows no enhancement but invades the duodenum.",  # a positive turn after "no"
    "The cyst has no septation and is enlarging.",
    "Oedema, which shows no enhancement.",
    "The biliary tree is not dilated; jaundice is likely due to hepatic infiltration.",
    "Soft tissue oedema at the base of the thumb without fluid collection.",
])
def test_positive_findings_stay_positive(clause):
    assert jev_pass.positive(clause)


async def test_w1n_not_asked_of_generated_normals(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"addressed": {"noul": 0.9}}, calls))
    report = "FINDINGS:\nA 3 cm pancreatic head mass. The scapholunate ligament maintains continuity.\nIMPRESSION:\nMass."
    jp = await jev_pass.run(inp(report, NUM_DICT), report)
    asked = [q["instructions"] for _, qs in calls for k, q in qs.items() if k.startswith("sup")]
    assert any("pancreatic head mass" in a for a in asked)
    assert not any("maintains continuity" in a for a in asked) and jp.support_error is None


# ── 3. every negatives check states its reason ──────────────────────────────

CHK_REPORT = ("FINDINGS:\nA 3 cm pancreatic head mass. The common bile duct measures 12 mm. No intrahepatic biliary "
              "dilatation. No hyperdense filling defect within the common bile duct, and no periampullary mass. "
              "The spleen is normal.\nIMPRESSION:\nPancreatic head mass.")
CHK_DICT = "- 3 cm pancreatic head mass\n- CBD 12 mm\n- periampullary mass"


async def test_check_items_state_their_reason_and_pointer(monkeypatch):
    def lab(kw):
        listing = kw["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1].splitlines()
        out = []
        for line in listing:
            n, text = line.split(". ", 1)
            if "intrahepatic" in text:
                out.append(f"{n} | implicated | CBD 12 mm | no")
            elif "periampullary" in text:
                out.append(f"{n} | contradicted | periampullary mass | no")
            elif "spleen" in text:
                out.append(f"{n} | implicated | - | no")
            else:
                out.append(f"{n} | default | - | no")
        return out
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(lab))
    items, _ = await negatives.classify_negatives(inp(CHK_REPORT, CHK_DICT), RUN)
    checks = [i for i in items if i.kind == "check"]
    assert len(checks) == 3
    for it in checks:
        assert it.evidence["check_reason"] in negatives.CHECK_REASONS and it.reason
        assert it.label != "Check: a dictated finding points here"
    by = {i.evidence["clause"]: i for i in checks}
    ih = next(v for k, v in by.items() if "intrahepatic" in k)
    assert ih.evidence["pointer"] == "CBD 12 mm" and "CBD 12 mm" in ih.label and "CBD 12 mm" in ih.reason
    pa = next(v for k, v in by.items() if "periampullary" in k)
    assert pa.cls == "action" and pa.evidence["check_reason"] == "conflict" and "periampullary mass" in pa.label
    # a conflict code can remove cleanly offers code's removal as a one-click (never pre-applied) edit
    assert pa.status == "open" and pa.edit is not None and pa.verified["unconfirmed"] is True
    fixed = verifier.apply_edit(CHK_REPORT, pa.edit, ["FINDINGS", "IMPRESSION"])
    assert "periampullary" not in fixed and "No hyperdense filling defect" in fixed
    sp = next(v for k, v in by.items() if "spleen" in k)                    # no pointer: still a stated reason
    assert sp.evidence["pointer"] == "" and sp.label == "Check: a dictated finding may affect this"


# ── 4. a brief option's own sentence grounds its insert ─────────────────────

OPT_REPORT = "FINDINGS:\nA 3 cm pancreatic head mass. The liver is normal.\nIMPRESSION:\nPancreatic head mass."


async def test_brief_option_negative_keeps_its_one_click_edit():
    opt = [{"id": "o1", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No duodenal wall thickening.",
            "reason": "staging"}]
    res = await engine.run_review(inp(OPT_REPORT, NUM_DICT, options=opt), RUN)
    it = next(i for i in res.items if i.lane == "additions")
    assert it.verified["code"] is True and "additions_new_content" not in it.verified["failed"]
    assert it.edit is not None and it.edit.mode == "insert" and it.edit.replace == "No duodenal wall thickening."
    assert it.status == "open" and not any(e["item_id"] == it.id for e in res.run["pre_apply"])   # one-click only


def test_option_sentence_grounds_only_its_own_negatives():
    from rapid_reports_ai.review_engine.items import Edit
    e = Edit(mode="insert", replace="No duodenal wall thickening.", section="FINDINGS")
    names = ["FINDINGS", "IMPRESSION"]
    args = (OPT_REPORT, e, "option", NUM_DICT, "")
    assert "additions_new_content" in verifier.guard_failures(*args, additions=True, sections=names)
    assert verifier.guard_failures(*args, additions=True, sections=names,
                                   extra_source="No duodenal wall thickening.",
                                   option_sentence="No duodenal wall thickening.") == []
    assert "additions_new_content" in verifier.guard_failures(
        *args, additions=True, sections=names, extra_source="No gallbladder mass.",
        option_sentence="No gallbladder mass.")


# ── 5. negatives-owned lane candidates held back from adjudication ──────────

PF_REPORT = "FINDINGS:\nA 3 cm pancreatic head mass. No ascites. The liver surface is smooth.\nIMPRESSION:\nMass."
PF_DICT = "- 3 cm pancreatic head mass\n- Ascites present\n- Hepatic capsule invasion"


def _contra_jev(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"c*": {"noul": 0.9}, "r*": {"noul": 0.9}, "d*": {"noul": 0.1},
                                         "addressed": {"noul": 0.9}}))


def _judged(calls):
    return [kw["user_prompt"].split("\n\nSTUDY TITLE")[0] for kw in calls]


async def test_owned_candidates_not_adjudicated_when_negatives_succeeds(monkeypatch):
    _contra_jev(monkeypatch)
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(MINOR, calls))
    res = await engine.run_review(inp(PF_REPORT, PF_DICT), RUN)
    judged = "\n".join(_judged(calls))
    assert "No ascites" not in judged and "liver surface" not in judged
    assert "pancreatic head mass" in judged                       # the positive clause is still judged
    assert res.run["cost"]["prefiltered"] >= 2 and "negatives" not in res.run["errors"]


async def test_held_candidates_adjudicated_when_negatives_fails(monkeypatch):
    _contra_jev(monkeypatch)
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(MINOR, calls))

    async def boom(**kw):
        raise RuntimeError("qwen down")
    monkeypatch.setattr(negatives, "_run_agent_with_model", boom)
    res = await engine.run_review(inp(PF_REPORT, PF_DICT), RUN)
    judged = "\n".join(_judged(calls))
    assert "No ascites" in judged and "liver surface" in judged and "negatives" in res.run["errors"]
    assert any("jev.contradiction" in i.detectors and "ascites" in (i.anchor.text.lower() if i.anchor else "")
               for i in res.items)
    assert res.run["cost"]["prefiltered"] == 0


async def test_prefilter_keeps_lanes_and_negatives_concurrent(monkeypatch):
    """The adjudicator runs while the classifier is still waiting on its model (no serialisation)."""
    started = asyncio.Event()

    async def adj_fake(**kw):
        started.set()
        class R:
            output = MINOR
        return R()

    async def slow_neg(**kw):
        await asyncio.wait_for(started.wait(), 2.0)          # times out (fails the classifier) if serialised
        class R:
            output = negatives.Labels(labels=_all_default(kw))
        return R()
    monkeypatch.setattr(adj, "_run_agent_with_model", adj_fake)
    monkeypatch.setattr(negatives, "_run_agent_with_model", slow_neg)
    res = await engine.run_review(inp(NUM_REPORT, NUM_DICT), RUN)
    assert started.is_set() and "negatives" not in res.run["errors"]
