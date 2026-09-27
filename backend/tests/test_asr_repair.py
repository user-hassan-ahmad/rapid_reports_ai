from __future__ import annotations

import pytest

from rapid_reports_ai.asr_repair import apply_fix, build_lexicon, candidates, content_words, phonetic_key

CAP = ["LUNGS", "LIVER", "SPLEEN", "PANCREAS", "ADRENAL GLANDS", "KIDNEYS", "BOWEL", "LYMPH NODES"]


def test_content_words_skip_function_words_numbers_and_units():
    words = [w for w, _, _ in content_words("There is a 14 mm nodule in the right upper lobe, measuring 5 millimetres.")]
    assert words == ["nodule", "right", "upper", "lobe"]  # 'measuring' is a verb, not a finding


def test_content_words_are_capped():
    assert len(content_words(" ".join(f"word{i}x" for i in range(30)).replace("0", "a"), cap=12)) == 12


def test_phonetic_key_groups_sound_alikes():
    assert phonetic_key("scold") == phonetic_key("skold")
    assert phonetic_key("skull") == phonetic_key("scull")


def _best(utterance, flagged, checklist=CAP):
    cs = candidates(utterance, flagged, build_lexicon(checklist))
    return [(c.heard.lower(), c.replacement.lower()) for c in cs]


@pytest.mark.parametrize("utterance, flagged, heard, replacement", [
    # Jev flags the neighbour ('glands' scored lowest); the fix is to 'renal'
    ("The renal glands are also normal.", "glands", "renal", "adrenal"),
    ("The common bowel duct measures 15 millimetres.", "bowel", "bowel", "bile"),
    ("No varospinal soft tissue abnormality.", "varospinal", "varospinal", "paraspinal"),
    ("There is a left paracetamol disc extrusion.", "paracetamol", "paracetamol", "paracentral"),
    ("No scold vault fractures are identified.", "scold", "scold", "skull"),
    ("Further, supplemental emboli are seen in the lingula.", "supplemental", "supplemental", "subsegmental"),
    ("in keeping with chronic smooth vessel ischaemic change.", "smooth", "smooth", "small"),
])
def test_candidates_include_the_true_word(utterance, flagged, heard, replacement):
    assert (heard, replacement) in _best(utterance, flagged)


def test_no_candidate_is_a_mere_inflection_of_the_heard_word():
    for heard, repl in _best("The kidneys are normal.", "kidneys"):
        assert repl.rstrip("s") != heard.rstrip("s")


def test_apply_fix_keeps_capitals_and_the_rest_of_the_sentence():
    cs = candidates("The renal glands are also normal.", "glands", build_lexicon(CAP))
    c = next(c for c in cs if c.replacement.lower() == "adrenal")
    assert apply_fix("The renal glands are also normal.", c) == "The adrenal glands are also normal."
    cs = candidates("Varospinal soft tissues are normal.", "Varospinal", build_lexicon(CAP))
    c = next(c for c in cs if c.replacement.lower() == "paraspinal")
    assert apply_fix("Varospinal soft tissues are normal.", c) == "Paraspinal soft tissues are normal."


def test_windows_never_swallow_a_function_word():
    for heard, repl in _best("The renal glands are also normal.", "glands"):
        assert heard.split()[0] not in ("the", "are") and heard.split()[-1] not in ("the", "are")


def test_a_candidate_never_just_deletes_a_heard_word():
    L = build_lexicon(["LIVER"])
    for u, f in [("The liver contains a 14 millimetre high lesion.", "high"),
                 ("Incidental hypodense marginal in the thyroid.", "marginal")]:
        for c in candidates(u, f, L):
            assert not set(c.replacement.lower().split()) < set(c.heard.lower().split())


def test_a_merged_negation_is_offered():
    # 'There is no pleural effusion' came out as 'There is nipple effusion'
    assert ("nipple", "no pleural") in _best("There is nipple effusion.", "nipple", ["LUNGS", "PLEURA"])


def test_a_fix_never_reduces_the_number_of_words():
    L = build_lexicon(["LUNGS", "PLEURA", "ADRENAL GLANDS"])
    for u, f in [("The common bowel duct measures 15 mm.", "bowel"), ("No varospinal soft tissue abnormality.", "varospinal"),
                 ("Further, supplemental emboli are seen.", "supplemental"), ("The liver contains a 14 millimetre high lesion.", "high")]:
        for c in candidates(u, f, L):
            assert len(c.replacement.split()) >= len(c.heard.split()), (c.heard, c.replacement)


def test_a_fix_never_doubles_a_neighbouring_word():
    from rapid_reports_ai.asr_repair import apply_fix
    u = "The common bowel duct measures 15 mm."
    for c in candidates(u, "bowel", build_lexicon([])):
        fixed = apply_fix(u, c).lower().split()
        assert all(a != b for a, b in zip(fixed, fixed[1:])), apply_fix(u, c)


# --- the chained choice: Jev picks the sentence -----------------------------------------------

import json as _json

import httpx as _httpx

from rapid_reports_ai.asr_repair import repair

STATE = {"scan_type": "CT chest, abdomen and pelvis", "checklist": CAP, "scratchpad": "The spleen is normal."}


def _jev(pick_containing: str | None, confidence: float = 0.9, calls: list | None = None):
    def handler(req):
        body = _json.loads(req.content)
        if calls is not None:
            calls.append(body)
        answers = {}
        for k, q in body["questions"].items():
            opts = q["criteria"]
            choice = next((o for o, s in opts.items() if pick_containing and pick_containing in s), "as_heard")
            answers[k] = {"type": "choice", "choice": choice, "confidence": confidence,
                          "probabilities": {o: (confidence if o == choice else 0.0) for o in opts}}
        return _httpx.Response(200, json={"answers": answers})
    return _httpx.MockTransport(handler)


async def test_no_flagged_word_means_no_call():
    calls = []
    r = await repair("The kidneys are normal.", (("kidneys", 0.97), ("normal", 0.96)), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev(None, calls=calls))
    assert (r.text, r.fixes, r.flags, calls) == ("The kidneys are normal.", [], [], [])


async def test_a_confident_choice_fixes_the_sentence():
    r = await repair("The renal glands are also normal.", (("renal", 0.81), ("glands", 0.37), ("normal", 0.73)),
                     state=STATE, lexicon=build_lexicon(CAP), api_key="k", transport=_jev("adrenal"))
    assert r.text == "The adrenal glands are also normal."
    assert [(f["heard"], f["replacement"]) for f in r.fixes] == [("renal", "adrenal")] and r.flags == []


async def test_a_hesitant_choice_flags_instead():
    r = await repair("The renal glands are also normal.", (("glands", 0.2),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev("adrenal", confidence=0.5))
    assert r.text == "The renal glands are also normal." and [f["word"] for f in r.flags] == ["glands"]


async def test_as_heard_is_respected():
    r = await repair("The renal glands are also normal.", (("glands", 0.2),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev(None))
    assert r.text == "The renal glands are also normal." and r.fixes == [] and len(r.flags) == 1


async def test_a_word_with_no_candidates_is_underlined_only_when_very_low_and_never_calls():
    calls = []
    r = await repair("The liver contains a 14 mm high lesion.", (("high", 0.38),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev(None, calls=calls))
    # 2026-09-27.3 trade-off: 'high' (hypo- or hyperdense) scored 0.38–0.44, above the underline band
    assert calls == [] and r.flags == []
    r = await repair("The liver contains a 14 mm high lesion.", (("high", 0.2),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev(None, calls=calls))
    assert calls == [] and [f["word"] for f in r.flags] == ["high"]


async def test_a_jev_failure_leaves_the_text_and_flags():
    t = _httpx.MockTransport(lambda req: _httpx.Response(502, text="bad"))
    r = await repair("The renal glands are also normal.", (("glands", 0.2),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=t)
    assert r.text == "The renal glands are also normal." and r.error and len(r.flags) == 1


async def test_the_chosen_option_maps_to_its_own_candidate(monkeypatch):
    # two candidates can produce the same sentence; the option → candidate map must stay aligned
    import rapid_reports_ai.asr_repair as ar
    c1 = ar.Candidate(4, 9, "renal", "adrenal", 0.9)
    c2 = ar.Candidate(4, 9, "renal", "adrenal", 0.8)  # same sentence as c1: collapsed into one option
    c3 = ar.Candidate(10, 16, "glands", "glandz", 0.7)
    monkeypatch.setattr(ar, "candidates", lambda s, w, lex, **kw: [c1, c2, c3])
    r = await repair("The renal glands are normal.", (("glands", 0.37),), state=STATE, lexicon=[],
                     api_key="k", transport=_jev("glandz"))
    assert r.text == "The renal glandz are normal."


def test_command_correction_and_discourse_words_are_never_asked_about():
    words = [w.lower() for w, _, _ in content_words("Sorry, let me see. Actually make that correction. Scratch that. New paragraph.")]
    assert words == []


async def test_only_a_very_low_score_is_underlined_when_nothing_was_fixed():
    r = await repair("The infundibulum is patent and the hepatic veins are normal.",
                     (("infundibulum", 0.45), ("hepatic", 0.2)), state=STATE, lexicon=build_lexicon([]),
                     api_key="k", transport=_jev(None))
    assert [f["word"] for f in r.flags] == ["hepatic"]  # 0.45 was searched for a fix but not underlined


def test_an_expansion_never_keeps_the_misheard_word_beside_its_correction():
    for heard, repl in _best("The renal glands are also normal.", "glands"):
        assert "renal adrenal" not in f"The renal glands".replace(heard, repl, 1).lower() or heard != "glands"
    fixed = [__import__("rapid_reports_ai.asr_repair", fromlist=["apply_fix"]).apply_fix("The renal glands are also normal.", c)
             for c in candidates("The renal glands are also normal.", "glands", build_lexicon(CAP))]
    assert not any("renal adrenal" in f.lower() for f in fixed)


async def test_each_choice_is_recorded_as_numbers():
    r = await repair("The renal glands are also normal.", (("glands", 0.2),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev("adrenal", confidence=0.9))
    assert len(r.decisions) == 1
    d = r.decisions[0]
    assert d["picked_candidate"] is True and d["probability"] == 0.9 and d["confidence"] == 0.9 and d["options"] >= 2


async def test_a_picked_but_unaccepted_fix_is_underlined_even_above_the_underline_band():
    # live: Jev chose 'adrenal' at p 0.77–0.81 but confidence 0.68–0.74; 'glands' scored 0.46
    r = await repair("The renal glands are also normal.", (("glands", 0.46),), state=STATE,
                     lexicon=build_lexicon(CAP), api_key="k", transport=_jev("adrenal", confidence=0.5))
    assert r.fixes == [] and [f["word"] for f in r.flags] == ["glands"]


async def test_a_neighbour_of_an_applied_fix_is_not_underlined():
    # live: 'nipple' → 'no pleural' applied, but 'effusion' (0.19, low only because of its
    # misheard neighbour) was still underlined
    r = await repair("There is nipple effusion.", (("nipple", 0.1), ("effusion", 0.19)), state=STATE,
                     lexicon=build_lexicon(["LUNGS", "PLEURA"]), api_key="k", transport=_jev("no pleural"))
    assert r.text == "There is no pleural effusion." and r.flags == []
