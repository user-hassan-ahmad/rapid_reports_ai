"""Linked normals: atoms + prose parser, prose<->atom link check, classifier-label routing, rendering, fallbacks."""
from __future__ import annotations

import pytest

from rapid_reports_ai import linked_normals as ln
from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import report_reconcile as rc

FIELD = [
    "- **Normal-study path:**",
    "  - N1 | A | The A is unremarkable.",
    "  - N2 | B | The B is unremarkable.",
    "  - N3 | C | The C is unremarkable.",
    "  - N4 | D | The D is unremarkable.",
    "  - N5 | X | No X in the D.",
    "  - N6 | Y | No Y.",
    "  - P1 | N1 N2 N3 | The A, B and C are unremarkable.",
    "  - P2 | N4 N5 | The D is unremarkable with no X.",
    "  - P3 | N6 | No Y.",
]


# ── parser ──────────────────────────────────────────────────────────────────

def test_parse_units_atoms_and_terms():
    lk = ln.parse_linked(FIELD)
    assert [u.pid for u in lk.units] == ["P1", "P2", "P3"]
    assert [[a.id for a in u.atoms] for u in lk.units] == [["N1", "N2", "N3"], ["N4", "N5"], ["N6"]]
    assert lk.units[1].atoms[1].term == "X" and lk.units[1].atoms[1].negative
    assert not any(u.problem for u in lk.units)


def test_parse_no_atoms_is_none_so_the_block_takes_the_per_line_path():
    assert ln.parse_linked(['- **Normal-study path:** "The A and B are unremarkable. No X."']) is None
    assert ln.parse_linked(["- **Normal-study path:**", "  - The A is unremarkable."]) is None


def test_parse_loose_lines_stay_sentences_never_dropped():
    lk = ln.parse_linked(FIELD[:3] + ["  - The Q is unremarkable. No Z.", "  - P1 | N1 N2 | The A and B are unremarkable."])
    assert lk.entries[0] == "The Q is unremarkable." and lk.entries[1] == "No Z."
    assert isinstance(lk.entries[2], ln.Unit)


def test_parse_orphan_atom_renders_as_itself_at_its_sweep_position():
    lines = FIELD[:7] + ["  - P1 | N1 N2 N3 | The A, B and C are unremarkable.", "  - P3 | N6 | No Y."]
    lk = ln.parse_linked(lines)
    assert [(u.pid, [a.id for a in u.atoms]) for u in lk.units] == [
        ("P1", ["N1", "N2", "N3"]), (None, ["N4"]), (None, ["N5"]), ("P3", ["N6"])]


def test_parse_unknown_or_repeated_id_marks_a_problem():
    lk = ln.parse_linked(FIELD[:4] + ["  - P1 | N1 N9 | The A and Q are unremarkable.", "  - P2 | N1 N2 | The A and B."])
    u1, u2 = lk.units[0], lk.units[1]
    assert [a.id for a in u1.atoms] == ["N1"] and u1.problem
    assert [a.id for a in u2.atoms] == ["N2"] and u2.problem
    assert ln.code_check(u1)[0] == "unknown or repeated atom id"


def test_parse_atom_on_the_bullet_line_and_quoted_sentences():
    lk = ln.parse_linked(['- **Normal-study path:** N1 | A | "The A is unremarkable."', '  - P1 | N1 | "The A is unremarkable."'])
    assert lk.units[0].prose == "The A is unremarkable." and lk.atoms[0].text == "The A is unremarkable."


def test_phrase_for_jev():
    assert ln.Atom("N1", "A", "The A is unremarkable.").phrase() == "the A is unremarkable"
    assert ln.Atom("N2", "X", "No X in the D.").phrase() == "there is no X in the D"


def test_strip_links_reduces_the_field_to_prose():
    sheet = "## Structural Pattern\n" + "\n".join(FIELD) + "\n- **Canonical default-normal lines:** x\n"
    out = ln.strip_links(sheet)
    assert '- **Normal-study path:** "The A, B and C are unremarkable. The D is unremarkable with no X. No Y."' in out
    assert "N1 |" not in out and "Canonical default-normal lines" in out
    plain = '## S\n- **Normal-study path:** "The A is unremarkable."\n'
    assert ln.strip_links(plain) == plain


# ── link check ──────────────────────────────────────────────────────────────

def _unit(k=0):
    return ln.parse_linked(FIELD).units[k]


def test_code_check_term_missing_and_measurement():
    u = ln.Unit("The A and the B are fine.", "P1", [ln.Atom("N1", "A", "The A is unremarkable."),
                                                    ln.Atom("N2", "C", "The C is unremarkable.")])
    assert ln.code_check(u) == ["term missing: N2 C"]
    u = ln.Unit("The A measures 5 mm.", "P1", [ln.Atom("N1", "A", "The A is unremarkable.")])
    assert "measurement" in ln.code_check(u)
    assert ln.code_check(_unit()) == []


@pytest.mark.parametrize("s,multi", [
    ("The A, B and C are unremarkable.", False),
    ("The kidneys are unremarkable with no hydronephrosis.", False),
    ("No free fluid.", False),
    ("The carpal ligaments are intact, the TFCC is normal.", True),
    ("The pelvic bones are unremarkable and the lung bases are clear.", True),
    ("The bones and soft tissues are unremarkable, no consolidation in the lung bases.", True),
    ("The portal vein is patent; the aorta is unremarkable.", True),
])
def test_multi_predicate(s, multi):
    assert ln.multi_predicate(s) is multi


def test_term_in_ignores_articles_only():
    assert ln.term_in("Hook of hamate", "The hook of the hamate is unremarkable.")
    assert not ln.term_in("ulna", "The ulnar nerve is unremarkable.")
    assert not ln.term_in("Lymph nodes", "No free fluid.")


@pytest.mark.parametrize("term,sentence", [
    ("Lymph nodes", "No lymphadenopathy."),                                   # Iteration 2: all 4 failures
    ("Mediastinal lymph nodes", "No mediastinal lymphadenopathy."),
    ("lymphadenopathy", "No enlarged lymph nodes."),
    ("Pelvic lymph nodes", "No enlarged pelvic nodes."),
    ("lymph node", "No lymphadenopathy."),
])
def test_term_in_equivalent_names(term, sentence):
    assert ln.term_in(term, sentence)


def test_term_equivalents_stay_narrow():
    assert not ln.term_in("Mediastinal lymph nodes", "No axillary lymphadenopathy.")   # modifier must still match
    assert not ln.term_in("nodes", "No lymphadenopathy.")                              # a bare "nodes" is not expanded
    assert ln.term_span("No mediastinal lymphadenopathy.", "Mediastinal lymph nodes") == (3, 30)
    assert ln.term_span("The A is unremarkable.", "B") is None


def test_code_check_passes_lymph_nodes_written_as_lymphadenopathy():
    u = ln.Unit("No lymphadenopathy.", "P1", [ln.Atom("N1", "lymph nodes", "No enlarged lymph nodes.")])
    assert ln.code_check(u) == []
    r = ln.render_unit(u, L(N1="default"), True, [], [])
    assert r.text[slice(*r.atoms[0]["span"])] == "lymphadenopathy"
    u = ln.Unit("The A is unremarkable with no lymphadenopathy.", "P1",
                [ln.Atom("N1", "A", "The A is unremarkable."), ln.Atom("N2", "lymph nodes", "No enlarged lymph nodes.")])
    r = ln.render_unit(u, L(N1="contradicted", N2="default"), True, [], [])
    assert (r.mode, r.text) == ("tail_only", "No lymphadenopathy.")


def test_code_check_flags_multi_predicate_prose():
    u = ln.Unit("The A is intact, the B is normal.", "P1", [ln.Atom("N1", "A", "The A is intact."),
                                                         ln.Atom("N2", "B", "The B is normal.")])
    assert ln.code_check(u) == ["multi-predicate"]


def test_link_questions_d1_per_atom_and_a1():
    qs = ln.link_questions(_unit(1))
    assert qs["d0"]["instructions"] == "Read only this sentence. It states that the D is unremarkable."
    assert qs["d1"]["instructions"] == "Read only this sentence. It states that there is no X in the D."
    assert qs["add"]["instructions"].endswith("other than: the D is unremarkable; there is no X in the D.")


@pytest.mark.parametrize("stated,added,ok,dropped", [
    ((0.95, 0.9, 0.85), 0.1, True, []),
    ((0.95, 0.79, 0.9), 0.1, False, ["N2"]),     # P(stated) < 0.80 -> dropped
    ((0.95, 0.9, 0.9), 0.30, False, []),         # P(added) >= 0.30 -> added
])
def test_link_verdict_thresholds(stated, added, ok, dropped):
    ans = {f"d{j}": {"noul": p} for j, p in enumerate(stated)} | {"add": {"noul": added}}
    v = ln.link_verdict(_unit(0), ans)
    assert (v["ok"], v["dropped"], v["jev"]) == (ok, dropped, "ok")


def test_link_verdict_jev_failure_falls_back_to_the_code_check():
    assert ln.link_verdict(_unit(0), None) == {"ok": True, "code": [], "dropped": [], "added": None, "jev": "error"}
    bad = ln.Unit("The A is fine.", "P1", [ln.Atom("N1", "A", "x"), ln.Atom("N2", "B", "y")])
    v = ln.link_verdict(bad, None)
    assert not v["ok"] and v["jev"] == "skipped"
    assert not ln.link_verdict(bad, {"d0": {"noul": 1}, "d1": {"noul": 1}, "add": {"noul": 0}})["ok"]


# ── labels ──────────────────────────────────────────────────────────────────

def test_parse_labels():
    got = ln.parse_labels(["1 | default | -", "2 | Implicated | CBD 12mm", "3 | bogus | -", "9 | default | -",
                           "2 | default | -"], 3)
    assert got == {1: {"cls": "default", "pointer": ""}, 2: {"cls": "implicated", "pointer": "CBD 12mm"}}
    assert ln.AtomLabels(labels='["1 | default | -"]').labels == ["1 | default | -"]


def test_classifier_prompts_reuse_the_review_engine_core():
    core = ln._classifier_core()
    assert core.startswith("The radiologist's convention") and "Step 2" in core and "contains a number" not in core
    assert core in ln.SEPARATE_SYS and core in ln.FOLD_SYS and "normal_labels" in ln.FOLD_SYS


# ── render ──────────────────────────────────────────────────────────────────

def L(**kw):
    return {k: {"cls": v, "pointer": "", "source": "t"} for k, v in kw.items()}


def test_render_all_default_is_verbatim_with_term_spans():
    r = ln.render_unit(_unit(0), L(N1="default", N2="default", N3="default"), True, [], [])
    assert (r.mode, r.text) == ("verbatim", "The A, B and C are unremarkable.")
    assert r.text[slice(*r.atoms[1]["span"])] == "B" and r.flagged == []


def test_render_implicated_is_grouped_with_its_label_and_term_span():
    r = ln.render_unit(_unit(0), L(N1="default", N2="implicated", N3="default"), True, [], [])
    assert (r.mode, r.text) == ("verbatim", "The A, B and C are unremarkable.")
    b = r.atoms[1]
    assert (b["label"], b["action"], b["own_line"]) == ("implicated", "implicated", False)
    assert r.text[slice(*b["span"])] == "B"
    # Subtraction removes only the atoms that cannot be asserted; implicated stays in the group.
    r = ln.render_unit(_unit(0), L(N1="contradicted", N2="implicated", N3="default"), True, [], [])
    assert (r.mode, r.text) == ("subtracted", "The B and C are unremarkable.")
    assert r.text[slice(*r.atoms[1]["span"])] == "B"


def test_render_contradicted_is_do_not_assert_and_dictated_is_left_out():
    r = ln.render_unit(_unit(1), L(N4="contradicted", N5="default"), True, [], [])
    assert (r.mode, r.text, r.flagged) == ("tail_only", "No X.", ["The D is unremarkable."])
    r = ln.render_unit(_unit(1), L(N4="default", N5="dictated"), True, [], [])
    assert (r.text, r.flagged) == ("The D is unremarkable.", [])
    assert r.atoms[1]["action"] == "dictated"


def test_render_link_failure_renders_atoms_one_line_each():
    r = ln.render_unit(_unit(0), L(N1="default", N2="default", N3="default"), False, [], [])
    assert (r.mode, r.text) == ("atoms", "The A is unremarkable. The B is unremarkable. The C is unremarkable.")
    assert r.text[slice(*r.atoms[2]["span"])] == "The C is unremarkable."


def test_render_unparseable_prose_with_a_removal_renders_kept_atoms():
    u = ln.Unit("Both A and B look fine.", "P1", [ln.Atom("N1", "A", "The A is unremarkable."),
                                                  ln.Atom("N2", "B", "The B is unremarkable.")])
    r = ln.render_unit(u, L(N1="default", N2="contradicted"), True, [], [])
    assert (r.mode, r.text) == ("atoms", "The A is unremarkable.")


def test_render_guards_dictated_negative_and_dictated_positive():
    # A default negative the dictation already says is left to the dictation (attempt-4 guard).
    u = ln.Unit("The kidneys are unremarkable with no hydronephrosis.", "P2",
                [ln.Atom("N4", "kidneys", "The kidneys are unremarkable."),
                 ln.Atom("N5", "hydronephrosis", "No hydronephrosis in the kidneys.")])
    r = ln.render_unit(u, L(N4="default", N5="default"), True, ["No hydronephrosis"], [])
    assert r.text == "The kidneys are unremarkable." and r.atoms[1]["action"] == "dictated"
    # A default structure a dictated positive finding names gets its own sentence.
    u = ln.Unit("The liver, spleen and pancreas are unremarkable.", "P1",
                [ln.Atom("N1", "liver", "The liver is unremarkable."), ln.Atom("N2", "spleen", "The spleen is unremarkable."),
                 ln.Atom("N3", "pancreas", "The pancreas is unremarkable.")])
    r = ln.render_unit(u, L(N1="default", N2="default", N3="default"), True, [], ["Small cyst in the spleen"])
    assert r.text == "The liver and pancreas are unremarkable. The spleen is unremarkable."
    assert r.atoms[1]["why"] == "named by a dictated finding" and r.atoms[1]["action"] == "keep"


def test_render_nothing_kept():
    r = ln.render_unit(_unit(2), L(N6="contradicted"), True, [], [])
    assert (r.mode, r.text, r.flagged) == ("none", None, ["No Y."])


def test_render_only_implicated_kept():
    r = ln.render_unit(_unit(2), L(N6="implicated"), True, [], [])
    assert (r.mode, r.text, r.atoms[0]["span"]) == ("verbatim", "No Y.", [3, 4])


# ── brief wiring ────────────────────────────────────────────────────────────

SHEET = '''# Skill Sheet: CT abdomen — test

## Structural Pattern
- **Sections:** FINDINGS, IMPRESSION
- **Normal-study path:**
  - N1 | liver | The liver is unremarkable.
  - N2 | intrahepatic biliary tree | The intrahepatic biliary tree is unremarkable.
  - N3 | spleen | The spleen is unremarkable.
  - N4 | kidneys | The kidneys are unremarkable.
  - N5 | hydronephrosis | No hydronephrosis.
  - N6 | free fluid | No free fluid.
  - P1 | N1 N2 N3 | The liver, intrahepatic biliary tree and spleen are unremarkable.
  - P2 | N4 N5 | The kidneys are unremarkable with no hydronephrosis.
  - P3 | N6 | No free fluid.
  - The visualised bones are unremarkable.

## Companion Matrix
- **Mandatory negatives:** (one line each)
  - "No free gas" (perforation)
'''


def _stub(monkeypatch, labels=None, jev_affected=frozenset(), link=None, link_fail=False, sep=None):
    """labels: classifier lines; link: prose -> {qid: p} overrides (default: all stated, nothing added)."""
    seen = {"states": [], "qwen_linked": []}

    async def fake_jev(state, questions):
        if state.startswith("SCAN TYPE"):
            seen["q"] = questions
            return {k: {"noul": 0.9 if k in jev_affected else 0.1} for k in questions}
        seen["states"].append(state)
        if link_fail:
            raise RuntimeError("jev down")
        ans = {k: {"noul": 0.95 if k.startswith("d") else 0.05} for k in questions}
        for k, p in ((link or {}).get(state) or {}).items():
            ans[k] = {"noul": p}
        return ans

    async def fake_qwen(state, negs, normals, measurements, linked=None):
        seen["qwen_linked"].append(linked)
        seen["normals"] = normals
        kw = dict(negatives=[rc.NegativeDecision(index=i, action="keep") for i in range(len(negs))],
                  affected_normals=[], applicable_measurements=[])
        if linked:
            return rc.QwenDecisionsLinked(**kw, normal_notes="n", normal_labels=labels or [])
        return rc.QwenDecisions(**kw)

    async def fake_label(scan_type, history, findings, atoms):
        seen["sep_atoms"] = [a.text for a in atoms]
        if sep is None:
            raise RuntimeError("labeller down")
        return sep

    async def no_split(negs):
        return [[n] for n in negs]

    async def no_plan(*a):
        raise RuntimeError("no plan")

    async def no_fallback(*a):
        return None
    monkeypatch.setenv("RR_GROUPED_NORMALS", "1")
    monkeypatch.setattr(qb, "_jev", fake_jev)
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    monkeypatch.setattr(qb, "_label_atoms", fake_label)
    monkeypatch.setattr(qb, "_split_bundled", no_split)
    monkeypatch.setattr(qb, "_plan", no_plan)
    monkeypatch.setattr(qb, "_fallback", no_fallback)
    return seen


def _path(b):
    return b.text.split("**Normal-study path:** ")[1].split("\n")[0]


DOUBLE_DUCT = "- Pancreatic head mass\n- CBD 12 mm\n- No ascites"
LABELS = ["1 | default | -", "2 | implicated | CBD 12 mm", "3 | default | -", "4 | default | -", "5 | default | -",
          "6 | dictated | No ascites"]


@pytest.mark.asyncio
async def test_brief_fold_labels_route_and_render(monkeypatch):
    monkeypatch.delenv("RR_LINKED_LABELLER", raising=False)
    seen = _stub(monkeypatch, labels=LABELS)
    b = await qb.compile_brief(SHEET, "CT", DOUBLE_DUCT, "Jaundice")
    # The atoms ride in the brief's reasoning-off Qwen call; the loose line takes the per-line path.
    sys_add, block = seen["qwen_linked"][0]
    assert sys_add == qb._ln.FOLD_SYS and "1. The liver is unremarkable." in block and "Jaundice" in block
    assert seen["normals"] == ["The visualised bones are unremarkable."]
    assert {"na0", "na5", "n0"} <= set(seen["q"])
    # One link request per prose sentence, the sentence as state.
    assert sorted(seen["states"]) == sorted(["The liver, intrahepatic biliary tree and spleen are unremarkable.",
                                             "The kidneys are unremarkable with no hydronephrosis.", "No free fluid."])
    assert _path(b) == ('"The liver, intrahepatic biliary tree and spleen are unremarkable. '
                        'The kidneys are unremarkable with no hydronephrosis. The visualised bones are unremarkable."')
    assert "Do not assert as normal" not in b.text
    assert '**Dictated negatives (state each as dictated):** "No ascites"' in b.text
    d0 = b.decisions["normals"][0]
    assert d0["linked"] and d0["mode"] == "verbatim" and d0["link"]["ok"]
    ihd = d0["atoms"][1]
    assert (ihd["label"], ihd["action"], ihd["pointer"]) == ("implicated", "implicated", "CBD 12 mm")
    path = _path(b).strip('"')
    assert path[slice(*ihd["path_span"])] == "intrahepatic biliary tree" and not ihd["own_line"]
    ff = b.decisions["normals"][2]
    assert ff["action"] == "do_not_assert" and ff["rendered"] is None and ff["atoms"][0]["action"] == "dictated"
    assert b.decisions["normals"][3] == {"text": "The visualised bones are unremarkable.", "action": "keep"}
    lk = b.decisions["linked"]
    assert (lk["labeller"], lk["n_atoms"], lk["n_units"], lk["n_loose"], lk["link_failed"]) == ("fold", 6, 3, 1, 0)


@pytest.mark.asyncio
async def test_brief_link_failure_renders_that_sentence_as_atoms(monkeypatch):
    seen = _stub(monkeypatch, labels=[f"{i} | default | -" for i in range(1, 7)],
                 link={"The kidneys are unremarkable with no hydronephrosis.": {"d1": 0.5}})
    b = await qb.compile_brief(SHEET, "CT", "Appendicitis")
    assert ("The liver, intrahepatic biliary tree and spleen are unremarkable. The kidneys are unremarkable. "
            "No hydronephrosis. No free fluid.") in _path(b)
    assert b.decisions["normals"][1]["link"]["dropped"] == ["N5"] and b.decisions["linked"]["link_failed"] == 1


@pytest.mark.asyncio
async def test_brief_jev_link_failure_falls_back_to_the_code_check(monkeypatch):
    sheet = SHEET.replace("P3 | N6 | No free fluid.", "P3 | N6 | No fluid.")    # term "free fluid" missing
    seen = _stub(monkeypatch, labels=[f"{i} | default | -" for i in range(1, 7)], link_fail=True)
    b = await qb.compile_brief(sheet, "CT", "Appendicitis")
    assert "No fluid." not in seen["states"]                     # a code failure is never sent to Jev
    v = [n["link"] for n in b.decisions["normals"] if n.get("linked")]
    assert [x["jev"] for x in v] == ["error", "error", "skipped"] and [x["ok"] for x in v] == [True, True, False]
    assert _path(b).startswith('"The liver, intrahepatic biliary tree and spleen are unremarkable. The kidneys are '
                               'unremarkable with no hydronephrosis. No free fluid.')


@pytest.mark.asyncio
async def test_brief_missing_labels_fall_back_to_jev_affected(monkeypatch):
    _stub(monkeypatch, labels=["1 | default | -"], jev_affected={"na1"})
    b = await qb.compile_brief(SHEET, "CT", "CBD 12 mm")
    atoms = b.decisions["normals"][0]["atoms"]
    assert [(a["label"], a["label_source"]) for a in atoms] == [("default", "fold"), ("contradicted", "jev_affected"),
                                                               ("default", "jev_affected")]
    assert '"The intrahepatic biliary tree is unremarkable."' in b.text.split("Do not assert as normal")[1]


@pytest.mark.asyncio
async def test_brief_classifier_default_upgraded_to_implicated_by_jev_affected(monkeypatch):
    _stub(monkeypatch, labels=[f"{i} | default | -" for i in range(1, 7)], jev_affected={"na2"})
    b = await qb.compile_brief(SHEET, "CT", "CBD 12 mm")
    sp = b.decisions["normals"][0]["atoms"][2]
    assert (sp["label"], sp["label_source"], sp["action"], sp["jev_affected"]) == ("implicated", "fold+jev", "implicated", 0.9)
    assert _path(b).startswith('"The liver, intrahepatic biliary tree and spleen are unremarkable.')
    assert b.decisions["linked"]["upgrades"] == ["N3 spleen (0.9)"]


@pytest.mark.asyncio
async def test_brief_separate_labeller(monkeypatch):
    monkeypatch.setenv("RR_LINKED_LABELLER", "separate")
    seen = _stub(monkeypatch, sep=LABELS)
    b = await qb.compile_brief(SHEET, "CT", DOUBLE_DUCT, "Jaundice")
    assert seen["qwen_linked"] == [None] and seen["sep_atoms"][1] == "The intrahepatic biliary tree is unremarkable."
    assert b.decisions["normals"][0]["atoms"][1]["label_source"] == "separate"
    # Labeller down: every atom falls back to Jev "affected".
    seen = _stub(monkeypatch, sep=None, jev_affected={"na1"})
    b = await qb.compile_brief(SHEET, "CT", DOUBLE_DUCT, "Jaundice")
    assert {a["label_source"] for n in b.decisions["normals"] if n.get("linked") for a in n["atoms"]} == {"jev_affected"}


@pytest.mark.asyncio
async def test_brief_without_atoms_takes_todays_per_line_path(monkeypatch):
    seen = _stub(monkeypatch, labels=[])
    sheet = SHEET.split("- **Normal-study path:**")[0] + '- **Normal-study path:** "The liver is unremarkable. No free fluid."\n'
    b = await qb.compile_brief(sheet, "CT", "Appendicitis")
    assert seen["qwen_linked"] == [None] and seen["states"] == []
    assert _path(b) == '"The liver is unremarkable. No free fluid."' and "linked" not in b.decisions


@pytest.mark.asyncio
async def test_flag_off_sends_the_unchanged_qwen_request(monkeypatch):
    seen = _stub(monkeypatch, labels=[])
    monkeypatch.delenv("RR_GROUPED_NORMALS")
    b = await qb.compile_brief(SHEET, "CT", "Appendicitis")
    assert seen["qwen_linked"] == [None] and seen["states"] == [] and not any(k.startswith("na") for k in seen["q"])
    assert "linked" not in b.decisions and "Dictated negatives" not in b.text


@pytest.mark.asyncio
async def test_reconcile_qwen_linked_none_is_the_production_request(monkeypatch):
    calls = []

    class R:
        output = None

    async def fake_run(**kw):
        calls.append(kw)
        return R()
    monkeypatch.setattr(rc, "_run_agent_with_model", fake_run)
    await rc._qwen("S", ["a"], ["b"], [])
    await rc._qwen("S", ["a"], ["b"], [], linked=("\nX", "BLOCK"))
    off, on = calls
    assert off["output_type"] is rc.QwenDecisions and off["system_prompt"] == rc.QWEN_SYS
    assert off["model_settings"]["max_tokens"] == 4000 and "BLOCK" not in off["user_prompt"]
    assert on["output_type"] is rc.QwenDecisionsLinked and on["system_prompt"] == rc.QWEN_SYS + "\nX"
    assert on["user_prompt"] == off["user_prompt"] + "\n\nBLOCK"


def test_plural_head_noun_before_a_locative_phrase():
    from rapid_reports_ai import normal_groups as ng
    assert ng.is_plural("extensor tendons at the wrist") and not ng.is_plural("ulnar nerve at Guyon's canal")
    assert ng.is_plural("lymph nodes in the pelvis") and not ng.is_plural("head of the femurs")
