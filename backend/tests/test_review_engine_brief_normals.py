"""Brief linked normals → review items (one owner): default → assumed_normal (info), implicated → check / uncertain
(minor); anchors on the atom's term in the FINAL report, unanchored when not found or ambiguous; dedupe against the
negatives classifier (brief wins on default / implicated; a classifier conflict / number / removal outranks).
Synthetic cases only, no live model calls."""
from rapid_reports_ai.review_engine import brief_normals as bn
from rapid_reports_ai.review_engine import engine, negatives
from rapid_reports_ai.review_engine.items import ReviewItem, Span, text_hash

from tests.review_engine_fakes import inp

P1 = "The liver, intrahepatic biliary tree and spleen are unremarkable."
P2 = "The kidneys are unremarkable with no hydronephrosis."
REPORT = (f"FINDINGS:\nPancreatic head mass. The CBD measures 12 mm. {P1} {P2}\n"
          "IMPRESSION:\nPancreatic head mass with biliary dilatation.")
DICT = "- Pancreatic head mass\n- CBD 12 mm\n- No ascites"


def _atom(i, term, label, action, text, span, pointer=""):
    return {"id": f"N{i}", "term": term, "text": text, "label": label, "label_source": "fold", "jev_affected": None,
            "pointer": pointer, "action": action, "own_line": False, "why": "", "span": span}


def _span(sentence, term):
    i = sentence.index(term)
    return [i, i + len(term)]


BRIEF = {"decisions": {"normals": [
    {"text": P1, "pid": "P1", "linked": True, "mode": "verbatim", "action": "keep", "rendered": P1, "atoms": [
        _atom(1, "liver", "default", "keep", "The liver is unremarkable.", _span(P1, "liver")),
        _atom(2, "intrahepatic biliary tree", "implicated", "implicated",
              "The intrahepatic biliary tree is unremarkable.", _span(P1, "intrahepatic biliary tree"), "CBD 12 mm"),
        _atom(3, "spleen", "default", "keep", "The spleen is unremarkable.", _span(P1, "spleen"))]},
    {"text": P2, "pid": "P2", "linked": True, "mode": "verbatim", "action": "keep", "rendered": P2, "atoms": [
        _atom(4, "kidneys", "default", "keep", "The kidneys are unremarkable.", _span(P2, "kidneys")),
        _atom(5, "hydronephrosis", "default", "keep", "No hydronephrosis.", _span(P2, "hydronephrosis"))]},
    {"text": "No free fluid.", "pid": "P3", "linked": True, "mode": "none", "action": "do_not_assert",
     "rendered": None, "atoms": [_atom(6, "free fluid", "dictated", "dictated", "No free fluid.", None)]},
    {"text": "The visualised bones are unremarkable.", "action": "keep"},
]}}
RUN = "00000000-0000-0000-0000-0000000000e1"


def _inp(report=REPORT, brief=BRIEF):
    i = inp(report, DICT)
    return i.model_copy(update={"artifacts": i.artifacts.model_copy(update={"brief": brief})})


def _by_term(items):
    return {i.evidence["term"]: i for i in items}


def test_default_and_implicated_atoms_become_items_anchored_on_their_terms():
    items = _by_term(bn.build_items(_inp(), RUN))
    assert set(items) == {"liver", "intrahepatic biliary tree", "spleen", "kidneys", "hydronephrosis"}
    for term, it in items.items():
        assert it.anchor.text == term and REPORT[it.anchor.start:it.anchor.end] == term
        assert it.anchor.text_hash == text_hash(REPORT) and it.detectors == [bn.DETECTOR]
        assert it.section == "FINDINGS" and it.status == "open"
    liver = items["liver"]
    assert (liver.kind, liver.cls, liver.label) == ("assumed_normal", "info", "Assumed normal")
    ihd = items["intrahepatic biliary tree"]
    assert (ihd.kind, ihd.cls) == ("check", "minor")
    assert ihd.evidence["check_reason"] == "uncertain" and ihd.evidence["pointer"] == "CBD 12 mm"
    assert ihd.evidence["included"] is True and "CBD 12 mm" in ihd.label


def test_dictated_and_do_not_assert_atoms_and_loose_lines_make_no_item():
    terms = {i.evidence["term"] for i in bn.build_items(_inp(), RUN)}
    assert "free fluid" not in terms and len(terms) == 5


def test_generator_re_merged_sentences_anchor_by_term_or_stay_unanchored():
    merged = ("FINDINGS:\nPancreatic head mass. The CBD measures 12 mm. The liver, spleen and intrahepatic biliary "
              "tree are unremarkable, and the kidneys are normal.\nIMPRESSION:\nPancreatic head mass.")
    items = _by_term(bn.build_items(_inp(merged), RUN))
    for term in ("liver", "spleen", "intrahepatic biliary tree", "kidneys"):
        a = items[term].anchor
        assert a is not None and merged[a.start:a.end] == term
    assert items["hydronephrosis"].anchor is None             # not in the final text: unanchored, never guessed


def test_ambiguous_term_is_unanchored():
    amb = REPORT.replace("Pancreatic head mass. ", "Pancreatic head mass. A 2 cm liver lesion. ", 1)
    amb = amb.replace(P1, P1.replace("The liver", "The liver parenchyma"))   # rendered sentence no longer verbatim
    items = _by_term(bn.build_items(_inp(amb), RUN))
    assert items["liver"].anchor is None                      # in an abnormal sentence too: never guessed
    assert items["spleen"].anchor is not None


def test_equivalent_name_anchors():
    rep = "FINDINGS:\nNo lymphadenopathy.\nIMPRESSION:\nNormal."
    brief = {"decisions": {"normals": [{"text": "No lymphadenopathy.", "pid": "P1", "linked": True, "mode": "verbatim",
                                        "rendered": "No lymphadenopathy.", "atoms": [
        _atom(1, "lymph nodes", "default", "keep", "No enlarged lymph nodes.", [3, 18])]}]}}
    it = bn.build_items(_inp(rep, brief), RUN)[0]
    assert it.anchor.text == "lymphadenopathy"


def test_no_linked_normals_no_items():
    assert bn.build_items(_inp(brief=None), RUN) == []
    assert bn.build_items(_inp(brief={"decisions": {"normals": [{"text": P1, "action": "keep"}]}}), RUN) == []


def _neg(kind, span, reason=None):
    s, e = span
    return ReviewItem(key="k", report_id="r", run_id=RUN, lane="accuracy", detectors=[negatives.DETECTOR], kind=kind,
                      cls="info", anchor=Span(start=s, end=e, text=REPORT[s:e]),
                      evidence={"check_reason": reason} if reason else {})


def test_dedupe_brief_wins_over_the_classifiers_same_verdict():
    brief = bn.build_items(_inp(), RUN)
    i = REPORT.index(P1)
    same = _neg("assumed_normal", (i, i + len(P1)))
    unc = _neg("check", (i, i + len(P1)), "uncertain")
    neg, kept, log = bn.dedupe([same, unc], brief)
    assert neg == [] and len(kept) == 5 and {d["dropped"] for d in log} == {same.id, unc.id}


def test_dedupe_classifier_conflict_outranks_the_brief_on_that_clause():
    brief = bn.build_items(_inp(), RUN)
    i = REPORT.index(P2)
    conflict = _neg("check", (i, i + len(P2)), "conflict")
    neg, kept, _ = bn.dedupe([conflict], brief)
    assert neg == [conflict]
    assert {b.evidence["term"] for b in kept} == {"liver", "intrahepatic biliary tree", "spleen"}


async def test_engine_one_item_per_brief_span(monkeypatch):
    """The engine emits the brief's items and drops the classifier's duplicates on the same clause."""
    import tests.test_review_engine_engine as te
    from rapid_reports_ai import report_reconcile as rc
    from rapid_reports_ai.review_engine import adjudicator as adj
    from tests.review_engine_fakes import jev, model
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(adj, "_run_agent_with_model", model(te.J))
    monkeypatch.setattr(negatives, "_run_agent_with_model", te.labels(te._all_default))
    res = await engine.run_review(_inp(), run_id=RUN)
    brief = [i for i in res.items if bn.DETECTOR in i.detectors]
    assert len(brief) == 5
    for b in brief:
        dup = [i for i in res.items if i is not b and i.anchor and b.anchor
               and i.anchor.start < b.anchor.end and b.anchor.start < i.anchor.end
               and i.kind in ("assumed_normal", "check")]
        assert dup == [], (b.evidence["term"], [(d.detectors, d.kind) for d in dup])
    assert any(d.get("source") == "brief_normals" for d in res.run["deduped"])


# ── a placeholder pointer ("->", "-", "—") is no pointer (prod 2026-10-06: 'Check: may not hold given “->”') ──

def test_placeholder_pointer_gives_the_generic_check_label():
    brief = {"decisions": {"normals": [
        {"text": P2, "pid": "P2", "linked": True, "mode": "verbatim", "action": "keep", "rendered": P2, "atoms": [
            _atom(4, "kidneys", "implicated", "implicated", "The kidneys are unremarkable.", _span(P2, "kidneys"),
                  "->")]}]}}
    it = _by_term(bn.build_items(_inp(brief=brief), RUN))["kidneys"]
    assert it.evidence["pointer"] == ""
    assert "->" not in it.label and "->" not in it.reason
    assert (it.label, it.reason) == negatives.check_text("uncertain", "")


def test_check_text_ignores_a_pointer_with_no_words():
    for p in ("->", "-", "—", " -> ", "…"):
        assert negatives.check_text("uncertain", p) == negatives.check_text("uncertain", "")
        assert negatives.check_text("conflict", p) == negatives.check_text("conflict", "")


def test_label_parsers_drop_placeholder_pointers():
    from rapid_reports_ai import linked_normals as ln
    got = ln.parse_labels(["1 | implicated | ->", "2 | default | —", "3 | implicated | CBD 12 mm"], 3)
    assert [got[i]["pointer"] for i in (1, 2, 3)] == ["", "", "CBD 12 mm"]
    got = negatives.parse_labels(["1 | implicated | -> | no", "2 | implicated | mass | yes"], 2)
    assert [got[i]["pointer"] for i in (1, 2)] == ["", "mass"]
