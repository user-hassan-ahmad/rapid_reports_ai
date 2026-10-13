"""Library matching v2 (spec §5): one Jev choice per finding over topics, exam-level binding per case, TNM in the same
per-finding request. jev_post is mocked throughout (no network)."""
import copy

import pytest

from rapid_reports_ai.hybrid_stack.copilot import library_match as LM
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L

from .conftest import TOY_ENTRY, TOY_REFERENCE


def _e(id_, topic, *, tier=2, purpose="Grades a thing.", modality=("CT",), finding=("lesion",), region=("chest",),
       aliases=(), trigger=("finding",), exam="", match_topic="", display=None, system=None, status="current"):
    d = copy.deepcopy(TOY_REFERENCE if tier == 2 else TOY_ENTRY)
    d.update(id=id_, topic=topic, purpose=purpose, trigger=list(trigger), exam=exam, match_topic=match_topic,
             display=display or f"{id_} 2020", system=system or f"{id_} system", aliases=list(aliases), status=status)
    d["applies_to"] = {"region": list(region), "modality": list(modality), "finding_type": list(finding),
                       "context": []}
    return d


def _lib(*entries):
    return L.Library({"version": "v-test", "entries": {f"{d['id']}@{d['version']}": {"entry": d} for d in entries}})


NODULE_A = _e("nod-a", "nodule", display="Nod A 2017", system="Nod A system", aliases=["nod a", "alpha"],
              purpose="Manages an incidental lung nodule in adults.", finding=("nodule",))
NODULE_B = _e("nod-b", "nodule", display="Nod B 2015", system="Nod B system", aliases=["alpha", "beta"],
              purpose="Manages an incidental lung nodule in adults.", finding=("nodule",), modality=("CT", "XR"))
COR_CAC = _e("cor-cac", "calcium", match_topic="coronary", display="CAC X", system="Calcium scoring",
             purpose="Scores coronary calcium.", finding=("coronary calcification",), region=("heart",),
             trigger=("exam", "finding"), exam="a dedicated calcium scoring CT")
COR_STEN = _e("cor-sten", "stenosis", match_topic="coronary", display="STEN Y", system="Stenosis reporting",
              purpose="Reports coronary stenosis on CT angiography.", finding=("coronary stenosis",),
              region=("heart",))
EXAM_ONLY = _e("ex-only", "exam-topic", trigger=("exam",), exam="an MRI of the knee", modality=("MRI",),
               display="Exam Only 2020")
XR_ONLY = _e("xr-only", "fracture", display="Frac Z", finding=("fracture",), modality=("XR",), region=("ankle",))
OLD = _e("old", "nodule", status="superseded")


@pytest.fixture(autouse=True)
def _clean():
    M.clear_cache()
    yield
    M.clear_cache()


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _jev(monkeypatch, answer, calls=None, target=LM):
    """answer(payload) -> answers dict (or raises)."""
    async def post(payload, key, timeout, transport=None):
        if calls is not None:
            calls.append(payload)
        return _Resp({"answers": answer(payload)})
    monkeypatch.setattr(target, "jev_post", post)


def _choice(c, conf=0.9):
    return {"choice": c, "confidence": conf}


def _tid(lib, entry_id):
    """The neutral choice id of the topic holding entry_id."""
    for i, group in enumerate(LM.topics(lib)):
        if any(e.id == entry_id for e in group):
            return f"t{i}"
    raise KeyError(entry_id)


# --- topics and option text ------------------------------------------------------------------------------------------

def test_topics_group_finding_entries_by_matcher_topic_and_skip_exam_only_and_superseded():
    lib = _lib(NODULE_A, NODULE_B, COR_CAC, COR_STEN, EXAM_ONLY, OLD)
    groups = [[e.id for e in g] for g in LM.topics(lib)]
    assert groups == [["cor-cac", "cor-sten"], ["nod-a", "nod-b"]]


def test_option_has_names_purpose_scope_and_no_eligibility():
    lib = _lib(XR_ONLY)
    (g,) = LM.topics(lib)
    assert LM.option(g) == ("Frac Z — xr-only system. Grades a thing. "
                            "(finding: fracture; region: ankle; imaging: XR)")


def test_option_for_siblings_dedupes_names_and_purposes_and_caps_names_at_four():
    lib = _lib(NODULE_A, NODULE_B)
    (g,) = LM.topics(lib)
    assert LM.option(g) == ("Nod A 2017 — Nod B 2015 — Nod A system — Nod B system. "
                            "Manages an incidental lung nodule in adults. "
                            "(finding: nodule; region: chest; imaging: CT / XR)")


def test_option_for_tier1_entry_carries_no_eligibility_or_scope_line():
    d = _e("toy-nodule", "toy", tier=1, purpose="Manages a toy nodule.")
    lib = _lib(d)
    (g,) = LM.topics(lib)
    text = LM.option(g)
    assert "eligib" not in text.lower() and "only" not in text and "not " not in text
    assert text.endswith("(finding: lesion; region: chest; imaging: CT)")


def test_coronary_entries_share_one_option():
    lib = _lib(COR_CAC, COR_STEN)
    (g,) = LM.topics(lib)
    text = LM.option(g)
    assert "CAC X" in text and "STEN Y" in text
    assert "Scores coronary calcium. Reports coronary stenosis on CT angiography." in text
    assert "finding: coronary calcification / coronary stenosis; region: heart" in text


def test_option_purpose_is_capped():
    lib = _lib(_e("long", "t", purpose="Word " * 60 + "end."), _e("long2", "t", purpose="Other " * 60 + "end."))
    (g,) = LM.topics(lib)
    purpose = LM.option(g).split(". ", 1)[1].rsplit(" (", 1)[0]
    assert len(purpose) <= LM.PURPOSE_MAX + 1


# --- case facts ------------------------------------------------------------------------------------------------------

def test_case_facts_parses_modality_and_exam_scores_and_caches(monkeypatch):
    lib = _lib(NODULE_A, COR_CAC, EXAM_ONLY)
    monkeypatch.setattr(L, "get", lambda: lib)
    calls = []
    exams = [e for e in lib.list() if "exam" in e.trigger]

    def ans(p):
        qs = p["questions"]
        assert qs["modality"]["type"] == "choice" and set(qs["modality"]["criteria"]) == set(LM.MODALITIES)
        assert "FINDING" not in p["state"] and p["state"].startswith("SCAN TYPE:\nCT calcium\n\nCLINICAL HISTORY:\n")
        out = {"modality": _choice("CT")}
        for i, e in enumerate(exams):
            assert qs[f"x_{i}"]["instructions"] == f"The study described in SCAN TYPE and CLINICAL HISTORY is: {e.exam}."
            out[f"x_{i}"] = {"noul": 0.9 if e.id == "cor-cac" else 0.2}
        return out
    _jev(monkeypatch, ans, calls)
    f = asyncio_run(LM.case_facts("CT calcium", "chest pain"))
    assert f.modality == "CT" and f.exams == {lib.lookup("cor-cac").key}
    asyncio_run(LM.case_facts("ct  CALCIUM", "Chest pain."))
    assert len(calls) == 1


def test_case_facts_failure_raises_and_caches_nothing(monkeypatch):
    monkeypatch.setattr(L, "get", lambda: _lib(COR_CAC))
    calls = []
    _jev(monkeypatch, lambda p: {"modality": {"bad": 1}}, calls)
    with pytest.raises(ValueError):
        asyncio_run(LM.case_facts("CT", ""))
    with pytest.raises(ValueError):
        asyncio_run(LM.case_facts("CT", ""))
    assert len(calls) == 2


# --- pick ------------------------------------------------------------------------------------------------------------

def _pick_ans(pick, conf=0.9, tnm_score=0.1, site="none"):
    def ans(p):
        out = {"tnm": {"noul": tnm_score}, "site": _choice(site)}
        if "pick" in p["questions"]:
            out["pick"] = _choice(pick, conf)
        return out
    return ans


def test_pick_state_and_questions(monkeypatch):
    lib = _lib(NODULE_A, XR_ONLY)
    monkeypatch.setattr(L, "get", lambda: lib)
    calls = []
    _jev(monkeypatch, _pick_ans("none"), calls)
    asyncio_run(LM.pick("CT chest", "", "A 7 mm nodule."))
    p = calls[0]
    assert p["state"] == "SCAN TYPE:\nCT chest\n\nCLINICAL HISTORY:\nnone given\n\nFINDING:\nA 7 mm nodule."
    q = p["questions"]
    assert q["pick"]["instructions"] == "Which guideline is meant for the FINDING?"
    assert set(q["pick"]["criteria"]) == {"t0", "t1", "none"}
    assert q["tnm"]["type"] == "noul"
    assert set(q["site"]["criteria"]) == {f"s{i}" for i in range(len(tnm.sites()))} | {"none"}


def test_pick_maps_topic_to_entries_and_caches(monkeypatch):
    lib = _lib(NODULE_A, NODULE_B, XR_ONLY)
    monkeypatch.setattr(L, "get", lambda: lib)
    calls = []
    _jev(monkeypatch, _pick_ans(_tid(lib, "nod-a")), calls)
    entries, site = asyncio_run(LM.pick("CT", "", "A nodule."))
    assert [e.id for e in entries] == ["nod-a", "nod-b"] and site is None
    asyncio_run(LM.pick("ct", "", "a nodule"))
    assert len(calls) == 1


@pytest.mark.parametrize("pick,conf", [("none", 0.99), ("t0", 0.49)])
def test_pick_none_or_below_floor_is_empty(monkeypatch, pick, conf):
    monkeypatch.setattr(L, "get", lambda: _lib(NODULE_A))
    _jev(monkeypatch, _pick_ans(pick, conf))
    assert asyncio_run(LM.pick("CT", "", "x")) == ([], None)


def test_pick_failure_raises_and_caches_nothing(monkeypatch):
    monkeypatch.setattr(L, "get", lambda: _lib(NODULE_A))
    calls = []
    _jev(monkeypatch, lambda p: {"tnm": {"noul": 0.1}, "site": _choice("none")}, calls)   # no "pick": malformed
    for _ in range(2):
        with pytest.raises(ValueError):
            asyncio_run(LM.pick("CT", "", "x"))
    assert len(calls) == 2


def test_pick_tnm_site_needs_a_high_tnm_score_and_a_site(monkeypatch):
    lib = _lib(NODULE_A)
    monkeypatch.setattr(L, "get", lambda: lib)
    s3 = tnm.sites()[3]
    _jev(monkeypatch, _pick_ans("none", tnm_score=0.9, site="s3"))
    assert asyncio_run(LM.pick("CT", "", "a mass")) == ([], s3)
    M.clear_cache()
    _jev(monkeypatch, _pick_ans("none", tnm_score=0.5, site="s3"))
    assert asyncio_run(LM.pick("CT", "", "a mass")) == ([], None)
    M.clear_cache()
    _jev(monkeypatch, _pick_ans("none", tnm_score=0.9, site="none"))
    assert asyncio_run(LM.pick("CT", "", "a mass")) == ([], None)


def test_modality_ok():
    lib = _lib(XR_ONLY, EXAM_ONLY)
    e = lib.lookup("xr-only")
    assert LM.modality_ok(e, None) and LM.modality_ok(e, "other") and LM.modality_ok(e, "XR")
    assert not LM.modality_ok(e, "CT")
    blank = _lib(_e("blank", "b", modality=())).lookup("blank")
    assert LM.modality_ok(blank, "CT")


# --- match() ---------------------------------------------------------------------------------------------------------

def _no_gptoss(monkeypatch):
    async def call(prompt):
        raise AssertionError("gpt-oss must not be called by match()")
    monkeypatch.setattr(M, "_call", call)


def _wire(monkeypatch, lib, modality="CT", bound=(), picks=None, facts_fail=False, tnm_score=0.1, site="none"):
    """One fake Jev endpoint for both request kinds: the case request (has "modality") and per-finding requests."""
    monkeypatch.setattr(L, "get", lambda: lib)
    _no_gptoss(monkeypatch)
    picks = picks or {}
    exams = [e for e in lib.list() if "exam" in e.trigger]
    calls = []

    def ans(p):
        qs = p["questions"]
        if "modality" in qs:
            if facts_fail:
                raise RuntimeError("down")
            out = {"modality": _choice(modality)}
            out.update({f"x_{i}": {"noul": 0.95 if e.id in bound else 0.05} for i, e in enumerate(exams)})
            return out
        finding = p["state"].rsplit("FINDING:\n", 1)[1]
        out = {"tnm": {"noul": tnm_score}, "site": _choice(site)}
        if "pick" in qs:
            got = picks.get(finding)
            out["pick"] = _choice(_tid(lib, got) if got else "none")
        return out
    _jev(monkeypatch, ans, calls)
    return calls


def test_match_makes_no_gptoss_call_and_returns_the_picked_pack(db_session, monkeypatch):
    lib = _lib(NODULE_A, NODULE_B)
    _wire(monkeypatch, lib, picks={"A 7 mm nodule.": "nod-a"})
    cards = asyncio_run(M.match(db_session, "CT chest", "", [M.Finding(id="u1", text="A 7 mm nodule.")]))
    assert [(c.key, c.finding_id, c.finding) for c in cards] == [("nod-a@1.0", "u1", "A 7 mm nodule.")]
    assert cards[0].siblings == ["nod-b@1.0"] and cards[0].reference is True


def test_modality_filter_drops_xr_only_pack_on_ct_but_keeps_it_when_modality_unknown(db_session, monkeypatch):
    lib = _lib(XR_ONLY)
    fs = [M.Finding(id="u1", text="Fracture.")]
    _wire(monkeypatch, lib, modality="CT", picks={"Fracture.": "xr-only"})
    assert asyncio_run(M.match(db_session, "CT ankle", "", fs)) == []
    M.clear_cache()
    _wire(monkeypatch, lib, facts_fail=True, picks={"Fracture.": "xr-only"})
    assert [c.key for c in asyncio_run(M.match(db_session, "CT ankle", "", fs))] == ["xr-only@1.0"]


def test_modality_filter_falls_through_to_the_next_entry_of_the_topic(db_session, monkeypatch):
    a = _e("ta", "t", modality=("US",), display="TA")
    b = _e("tb", "t", modality=("CT",), display="TB")
    lib = _lib(a, b)
    _wire(monkeypatch, lib, modality="CT", picks={"x": "ta"})
    cards = asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="x")]))
    assert [c.key for c in cards] == ["tb@1.0"]


def test_exam_card_created_on_bound_exam_with_dictation_as_finding(db_session, monkeypatch):
    lib = _lib(NODULE_A, EXAM_ONLY)
    _wire(monkeypatch, lib, modality="CT", bound={"ex-only"})   # modality CT, exam pack is MRI: never filtered
    cards = asyncio_run(M.match(db_session, "MRI knee", "", [M.Finding(id="u1", text="Effusion.")],
                                dictation="Effusion. Menisci intact."))
    assert [(c.key, c.finding_id, c.finding, c.why, c.known, c.status) for c in cards] == [
        ("ex-only@1.0", "exam", "Effusion. Menisci intact.", "", True, "verified")]


def test_exam_card_finding_defaults_to_joined_finding_texts(db_session, monkeypatch):
    lib = _lib(EXAM_ONLY)
    _wire(monkeypatch, lib, bound={"ex-only"})
    cards = asyncio_run(M.match(db_session, "MRI knee", "", [M.Finding(id="u1", text="A."), M.Finding(id="u2", text="B.")]))
    assert cards[0].finding == "A.\nB."


def test_finding_pick_of_an_exam_carried_pack_merges(db_session, monkeypatch):
    lib = _lib(COR_CAC, COR_STEN)
    _wire(monkeypatch, lib, bound={"cor-cac"}, picks={"Calcified plaque.": "cor-cac"})
    cards = asyncio_run(M.match(db_session, "CT calcium score", "", [M.Finding(id="u1", text="Calcified plaque.")]))
    assert [(c.key, c.finding_id) for c in cards] == [("cor-cac@1.0", "exam")]


CADRADS = _e("cad-x", "stenosis", match_topic="coronary", display="CADX", trigger=("exam",),
              exam="a coronary CT angiogram", region=("heart",))


def test_ctca_coronary_finding_merges_into_the_exam_card_and_gives_no_calcium_card(db_session, monkeypatch):
    lib = _lib(COR_CAC, CADRADS)          # CAC: exam + finding; CADX: exam only; both match_topic "coronary"
    _wire(monkeypatch, lib, bound={"cad-x"}, picks={"Calcified plaque.": "cor-cac"})
    cards = asyncio_run(M.match(db_session, "CT coronary angiogram", "", [M.Finding(id="u1", text="Calcified plaque.")]))
    assert [(c.key, c.finding_id) for c in cards] == [("cad-x@1.0", "exam")]


def test_calcium_scan_coronary_finding_merges_into_the_calcium_exam_card(db_session, monkeypatch):
    lib = _lib(COR_CAC, CADRADS)
    _wire(monkeypatch, lib, bound={"cor-cac"}, picks={"Calcified plaque.": "cor-cac"})
    cards = asyncio_run(M.match(db_session, "CT calcium score", "", [M.Finding(id="u1", text="Calcified plaque.")]))
    assert [(c.key, c.finding_id) for c in cards] == [("cor-cac@1.0", "exam")]


def test_coronary_finding_without_a_bound_exam_gets_the_calcium_card(db_session, monkeypatch):
    lib = _lib(COR_CAC, CADRADS)
    _wire(monkeypatch, lib, picks={"Calcified plaque.": "cor-cac"})
    cards = asyncio_run(M.match(db_session, "CT chest", "", [M.Finding(id="u1", text="Calcified plaque.")]))
    assert [(c.key, c.finding_id) for c in cards] == [("cor-cac@1.0", "u1")]


def test_exam_cards_count_toward_the_case_cap(db_session, monkeypatch):
    exams = [_e(f"ex{i}", f"ex{i}", trigger=("exam",), exam=f"study {i}") for i in range(M.MAX_PER_CASE - 1)]
    lib = _lib(*exams, NODULE_A, XR_ONLY)
    _wire(monkeypatch, lib, modality="other", bound={e["id"] for e in exams},
          picks={"n": "nod-a", "f": "xr-only"})
    cards = asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="n"), M.Finding(id="u2", text="f")]))
    assert len(cards) == M.MAX_PER_CASE
    assert [c.finding_id for c in cards][-1] == "u1"


def test_one_finding_failure_gives_no_card_for_it_only(db_session, monkeypatch):
    lib = _lib(NODULE_A, XR_ONLY)
    calls = _wire(monkeypatch, lib, modality="other", picks={"n": "nod-a", "f": "xr-only"})
    real = LM.jev_post

    async def flaky(payload, key, timeout, transport=None):
        if payload["state"].endswith("FINDING:\nf"):
            raise RuntimeError("down")
        return await real(payload, key, timeout, transport)
    monkeypatch.setattr(LM, "jev_post", flaky)
    cards = asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="n"), M.Finding(id="u2", text="f")]))
    assert [c.key for c in cards] == ["nod-a@1.0"]


# --- TNM in the per-finding request ----------------------------------------------------------------------------------

def _gate(monkeypatch, score):
    calls = []

    async def gate(finding, site, history):
        calls.append(site)
        return score
    monkeypatch.setattr(M, "_gate", gate)
    return calls


def test_tnm_low_uses_no_site_and_calls_no_gate(db_session, monkeypatch):
    _wire(monkeypatch, _lib(NODULE_A), tnm_score=0.5, site="s0")
    g = _gate(monkeypatch, 0.99)
    assert asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="m")])) == []
    assert g == []


def test_tnm_high_with_site_gates_once_and_cards_on_pass(db_session, monkeypatch):
    site = tnm.sites()[0]
    _wire(monkeypatch, _lib(NODULE_A), tnm_score=0.9, site="s0")
    g = _gate(monkeypatch, 0.9)
    cards = asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="m")]))
    assert g == [site] and [c.key for c in cards] == [tnm.entry(site).key]
    assert cards[0].finding_id == "u1"


def test_tnm_gate_fail_gives_no_tnm_card(db_session, monkeypatch):
    _wire(monkeypatch, _lib(NODULE_A), tnm_score=0.9, site="s0")
    g = _gate(monkeypatch, 0.2)
    assert asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="m")])) == []
    assert len(g) == 1


def test_tnm_site_none_calls_no_gate(db_session, monkeypatch):
    _wire(monkeypatch, _lib(NODULE_A), tnm_score=0.9, site="none")
    g = _gate(monkeypatch, 0.99)
    assert asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="m")])) == []
    assert g == []


def test_tnm_and_library_card_on_one_finding_rank_tnm_first(db_session, monkeypatch):
    site = tnm.sites()[0]
    _wire(monkeypatch, _lib(NODULE_A), tnm_score=0.9, site="s0", picks={"m": "nod-a"})
    _gate(monkeypatch, 0.9)
    cards = asyncio_run(M.match(db_session, "CT", "", [M.Finding(id="u1", text="m")]))
    assert [c.key for c in cards] == [tnm.entry(site).key, "nod-a@1.0"]


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
