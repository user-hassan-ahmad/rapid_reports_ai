"""Brief linked normals → review items (one owner): default → assumed_normal (info, green), implicated →
assumed_normal (info, amber: evidence.form "negative"); anchors on the atom's term in the FINAL report, unanchored when not found or ambiguous; dedupe against the
negatives classifier (brief wins on default / implicated; a classifier conflict / number / removal outranks).
Synthetic cases only, no live model calls."""
import pytest

from rapid_reports_ai import brief_anchor
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
    assert (ihd.kind, ihd.cls, ihd.label) == ("assumed_normal", "info", negatives.AMBER)
    assert ihd.evidence["form"] == "negative" and ihd.evidence["pointer"] == "CBD 12 mm"
    assert ihd.evidence["included"] is True and "CBD 12 mm" in ihd.reason


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
    """The engine emits the brief's items and the classifier makes none on the clauses the brief owns."""
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
    assert res.run["negatives"]["owned_by_brief"] >= 2      # owned: the classifier makes no item, nothing to dedupe


def _engine_stubs(monkeypatch, calls):
    import tests.test_review_engine_engine as te
    from rapid_reports_ai import report_reconcile as rc
    from rapid_reports_ai.review_engine import adjudicator as adj
    from tests.review_engine_fakes import jev, model
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(adj, "_run_agent_with_model", model(te.J))
    fake = te.labels(te._all_default)

    async def spy(**kw):
        calls.append(kw)
        return await fake(**kw)
    monkeypatch.setattr(negatives, "_run_agent_with_model", spy)


async def test_engine_classifier_never_sees_brief_owned_statements(monkeypatch):
    """Latency (prod d3d1e0a5, negatives_wait 7.6 s): statements the brief already labelled are not re-classified;
    the brief's items still own them."""
    calls = []
    _engine_stubs(monkeypatch, calls)
    res = await engine.run_review(_inp(), run_id=RUN)
    if calls:
        listing = calls[0]["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1]
        assert P1 not in listing and "No hydronephrosis" not in listing and "kidneys" not in listing
    assert res.run["negatives"]["owned_by_brief"] >= 2
    assert len([i for i in res.items if bn.DETECTOR in i.detectors]) == 5


async def test_engine_brief_build_failure_classifies_everything(monkeypatch):
    calls = []
    _engine_stubs(monkeypatch, calls)

    def broken(*a, **k):
        raise RuntimeError("bad brief")
    monkeypatch.setattr(bn, "build_items", broken)
    res = await engine.run_review(_inp(), run_id=RUN)
    assert "brief_normals" in res.run["errors"]
    assert P1 in calls[0]["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1]
    assert res.run["negatives"]["owned_by_brief"] == 0


def test_brief_items_carry_their_form():
    items = _by_term(bn.build_items(_inp(), RUN))
    assert items["liver"].evidence["form"] == "normal"
    assert items["intrahepatic biliary tree"].evidence["form"] == "negative"    # implicated: the amber tint
    assert "check_reason" not in items["intrahepatic biliary tree"].evidence
    assert items["hydronephrosis"].evidence["form"] == "negative"


# ── a placeholder pointer ("->", "-", "—") is no pointer (prod 2026-10-06: 'Check: may not hold given “->”') ──

def test_placeholder_pointer_gives_the_generic_check_label():
    brief = {"decisions": {"normals": [
        {"text": P2, "pid": "P2", "linked": True, "mode": "verbatim", "action": "keep", "rendered": P2, "atoms": [
            _atom(4, "kidneys", "implicated", "implicated", "The kidneys are unremarkable.", _span(P2, "kidneys"),
                  "->")]}]}}
    it = _by_term(bn.build_items(_inp(brief=brief), RUN))["kidneys"]
    assert it.evidence["pointer"] == ""
    assert "->" not in it.label and "->" not in it.reason
    assert (it.label, it.reason, it.evidence["form"]) == negatives.ai_layer("implicated", "")


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


# ── items, conflict cards and owned spans from quality_check.anchors (spec 2026-10-09) ──

AREPORT = ("FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion. "
           "The liver is unremarkable. No paratracheal or subcarinal lymphadenopathy. No pulmonary emboli. "
           "No pneumothorax. No pericardial effusion.\n\n"
           "IMPRESSION:\nSmall right effusion.\n")


def _anc(ref, action, source, text, how="term+jev", pointer="", unit=None, report=AREPORT):
    i = report.index(text)
    unit = unit or next(u.text for u in brief_anchor.units(report) if text in u.text)
    u0 = report.index(unit)
    return {"ref": ref, "action": action, "source": source, "pointer": pointer, "how": how,
            "span": [i, i + len(text)], "span_text": text, "unit": unit, "offset": i - u0, "dupes": 1}


ANCHORS = [
    _anc("neg:1", "keep", "finding:Pleural effusion", "contralateral pleural effusion", pointer="Pleural effusion"),
    _anc("atom:P2:N3", "keep", "atom", "liver"),
    _anc("atom:P1:N2", "implicated", "atom", "No paratracheal or subcarinal lymphadenopathy.", how="jev",
         pointer="right hilar nodes"),
    _anc("dict:0", "dictated", "dictated", "pulmonary emboli"),
    _anc("neg:2", "keep", "sheet", "pneumothorax"),                 # kept sheet negative: the classifier's call
    _anc("neg:3", "dictated", "sheet", "pericardial effusion"),     # dictated sheet negative: owned, no item
    {"ref": "neg:6", "action": "keep", "source": "sheet", "pointer": "", "how": "none", "span": None,
     "span_text": "", "unit": "", "offset": 0},
]


def _ainp(qc):
    i = inp(AREPORT, "- Small right pleural effusion\n- No pulmonary emboli", quality_check=qc)
    return i.model_copy(update={"artifacts": i.artifacts.model_copy(update={"brief": {"decisions": {}}})})


def test_items_come_from_anchors_with_tint_by_origin():
    items = {i.evidence["ref"]: i for i in bn.build_items(_ainp({"anchors": ANCHORS}), RUN)}
    assert set(items) == {"neg:1", "atom:P2:N3", "atom:P1:N2"}         # dictated: no item; unanchored: none
    assert items["neg:1"].evidence["form"] == "negative" and items["neg:1"].evidence["pointer"] == "Pleural effusion"
    assert items["atom:P2:N3"].evidence["form"] == "normal" and items["atom:P2:N3"].kind == "assumed_normal"
    assert items["atom:P1:N2"].evidence["form"] == "negative" and items["atom:P1:N2"].kind == "assumed_normal"
    for it in items.values():
        assert AREPORT[it.anchor.start:it.anchor.end] == it.anchor.text


def test_a_brief_conflict_is_a_check_card_and_replaces_the_tint_on_its_clause():
    qc = {"anchors": ANCHORS, "brief_conflicts": [
        {"clause": "No contralateral pleural effusion.", "refs": ["neg:1"], "reason": "brief_kept", "score": 0.8,
         "source": "finding:Pleural effusion", "pointer": "Pleural effusion"}]}
    items = bn.build_items(_ainp(qc), RUN)
    cards = [i for i in items if i.kind == "check"]
    assert len(cards) == 1 and cards[0].evidence["check_reason"] == "conflict"
    assert cards[0].evidence["brief_reason"] == "brief_kept"
    assert not any(i.kind == "assumed_normal" and i.evidence.get("ref") == "neg:1" for i in items)


def test_owned_spans_cover_every_anchor_including_dictated():
    spans = bn.owned_spans(_ainp({"anchors": ANCHORS}))
    texts = {AREPORT[a:b] for a, b in spans}
    assert "pulmonary emboli" in texts and "liver" in texts and len(spans) == 5      # not neg:2 (kept sheet)


def test_old_reports_without_anchors_use_the_legacy_path():
    assert bn.owned_spans(_inp()) is None
    assert {i.evidence["term"] for i in bn.build_items(_inp(), RUN)}     # legacy items still built


def test_split_and_removal_blocked_cards_have_their_own_wording():
    qc = {"anchors": ANCHORS, "brief_conflicts": [
        {"clause": "No paratracheal or subcarinal lymphadenopathy.", "refs": ["atom:P1:N2"], "reason": "brief_split",
         "score": 0.6, "source": "atom", "pointer": "", "action": "omit"},
        {"clause": "The liver is unremarkable.", "refs": [], "reason": "removal_blocked", "score": 0.9,
         "source": "", "pointer": "", "why": "carries"}]}
    cards = {c.evidence["brief_reason"]: c for c in bn.build_items(_ainp(qc), RUN) if c.kind == "check"}
    assert set(cards) == {"brief_split", "removal_blocked"}
    assert "kept part of this and advised against part" in cards["brief_split"].reason
    assert "not removed automatically" in cards["removal_blocked"].reason
    for c in cards.values():
        assert c.cls == negatives.CLS["conflict"] and AREPORT[c.anchor.start:c.anchor.end] == c.anchor.text


async def test_owned_spans_drive_the_engine_classifier(monkeypatch):
    """With anchors, `owned` is the anchors' spans (incl. dictated), not the legacy atom anchors."""
    _engine_stubs(monkeypatch, [])
    seen = {}
    real = engine._negatives

    async def spy(inp_, run_id, types=None, owned=None):
        seen["owned"] = owned
        return await real(inp_, run_id, types, owned)
    monkeypatch.setattr(engine, "_negatives", spy)
    await engine.run_review(_ainp({"anchors": ANCHORS}), run_id=RUN)
    assert seen["owned"] == bn.owned_spans(_ainp({"anchors": ANCHORS}))


DUP = ("FINDINGS:\nA right lung mass, with No pulmonary emboli. seen. No pulmonary emboli.\n\n"
       "IMPRESSION:\nMass.\n")


def test_anchor_relocation_takes_only_whole_units_never_a_copy_inside_a_longer_sentence():
    real = DUP.rindex("No pulmonary emboli.")
    a = {"ref": "neg:1", "action": "keep", "source": "finding:Right lung mass", "pointer": "", "how": "jev",
         "span": [real + 9, real + 29], "span_text": "No pulmonary emboli.", "unit": "No pulmonary emboli.",
         "offset": 0, "dupes": 1}                       # stored position stale: relocation needed
    i = inp(DUP, "- Right lung mass", quality_check={"anchors": [a]})
    assert DUP.find("No pulmonary emboli.") < real    # the first textual hit is inside the longer sentence
    assert bn.owned_spans(i) == [(real, real + len("No pulmonary emboli."))]


def test_a_changed_duplicate_count_leaves_the_anchor_unplaced():
    rep = ("FINDINGS:\nA right lung mass measuring 3 cm. No pulmonary emboli. The liver is unremarkable. "
           "No pulmonary emboli.\n\nIMPRESSION:\nMass.\n")
    a = {"ref": "neg:1", "action": "keep", "source": "finding:Right lung mass", "pointer": "", "how": "jev",
         "span": [44, 64], "span_text": "No pulmonary emboli.", "unit": "No pulmonary emboli.", "offset": 0,
         "dupes": 1}                                    # one copy when anchored, two now: which is ours is unknowable
    i = inp(rep, "- Right lung mass", quality_check={"anchors": [a]})
    assert bn.owned_spans(i) == []
    assert [it.anchor for it in bn.build_items(i, RUN)] == [None]   # unanchored, never guessed


def test_owned_spans_include_conflict_card_clauses():
    qc = {"anchors": ANCHORS, "brief_conflicts": [
        {"clause": "A small right pleural effusion.", "refs": [], "reason": "removal_blocked", "score": 0.9,
         "source": "", "pointer": "", "why": "carries"}]}
    texts = {AREPORT[a:b] for a, b in bn.owned_spans(_ainp(qc))}
    assert "A small right pleural effusion" in texts


def test_a_conflict_card_whose_clause_is_gone_is_unanchored_with_no_edit():
    qc = {"anchors": ANCHORS, "brief_conflicts": [
        {"clause": "No ascites.", "refs": ["neg:9"], "reason": "brief_kept", "score": 0.7, "source": "sheet",
         "pointer": ""}]}
    (card,) = [c for c in bn.build_items(_ainp(qc), RUN) if c.kind == "check"]
    assert card.anchor is None and card.edit is None and card.section is None


async def test_a_removal_blocked_clause_is_not_reclassified_and_its_brief_card_survives(monkeypatch):
    calls = []
    _engine_stubs(monkeypatch, calls)
    clause = "No pulmonary emboli."
    qc = {"anchors": [a for a in ANCHORS if a["ref"] != "dict:0"], "brief_conflicts": [
        {"clause": clause, "refs": [], "reason": "removal_blocked", "score": 0.9, "source": "", "pointer": "",
         "why": "carries"}]}
    res = await engine.run_review(_ainp(qc), run_id=RUN)
    for c in calls:
        assert clause not in c["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1]
    cards = [i for i in res.items if bn.DETECTOR in i.detectors and i.kind == "check"]
    assert [c.evidence["brief_reason"] for c in cards] == ["removal_blocked"]


def test_a_kept_sheet_negative_is_not_owned_and_makes_no_brief_item():
    """The brief owns selection and what it labels reliably; the classifier owns default-vs-implicated salience for
    sheet negatives the brief merely kept (lab b204edc: brief implicated recall 7/58)."""
    i = _ainp({"anchors": ANCHORS})
    texts = {AREPORT[a:b] for a, b in bn.owned_spans(i)}
    assert "pneumothorax" not in texts
    assert "neg:2" not in {it.evidence.get("ref") for it in bn.build_items(i, RUN)}
    for action in ("default", "implicated"):
        a = {**ANCHORS[5], "action": action}
        assert bn.owned_spans(_ainp({"anchors": [a]})) == [] and bn.build_items(_ainp({"anchors": [a]}), RUN) == []


def test_finding_linked_and_dictated_sheet_negatives_stay_owned():
    i = _ainp({"anchors": ANCHORS})
    texts = {AREPORT[a:b] for a, b in bn.owned_spans(i)}
    assert {"contralateral pleural effusion", "pericardial effusion"} <= texts
    items = {it.evidence.get("ref"): it for it in bn.build_items(i, RUN)}
    assert items["neg:1"].evidence["form"] == "negative" and "neg:3" not in items


@pytest.mark.parametrize("why,text", [
    ("sentence_type", "the sentence also states other content"),
    ("sentence_unread", "could not be checked safely for automatic removal"),
    ("brief_anchor", "but the brief kept it"),
    ("semicolon", "the sentence couldn't be edited automatically"),
    ("not_whole", "the sentence couldn't be edited automatically"),
])
def test_removal_blocked_card_text_follows_the_block_reason(why, text):
    label, reason = bn._conflict_text({"reason": "removal_blocked", "why": why})
    assert reason.startswith("Contradicts your dictation") and text in reason
    assert reason.endswith("Remove it, or dismiss to keep it.")
    assert "pertinent" not in reason
