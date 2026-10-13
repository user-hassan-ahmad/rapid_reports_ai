import pytest

from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Entry, GuidelineContent, Publication

pytestmark = pytest.mark.usefixtures("web_fetch_on")   # these tests exercise the web path

U = [M.Finding(id="u1", text="8 mm part-solid nodule right upper lobe."), M.Finding(id="u2", text="Simple renal cyst.")]


@pytest.fixture(autouse=True)
def _clean():
    M.clear_cache()
    yield
    M.clear_cache()


def _raw(**per):
    return M.RawMatch(findings=[M.RawFinding(id=k, systems=v) for k, v in per.items()])


def _sys(name, version="2017", branch="Subsolid", skeleton=("Solid", "Subsolid")):
    return M.RawSystem(name=name, version=version, why="w", branch=branch, skeleton=list(skeleton),
                       publication=M.Publication(title="T", year=version))


def _put(db, key, name, version, aliases=(), branches=(), status="draft", applies_to="", year=""):
    row = R.upsert(db, key=key, name=name, version=version, aliases=list(aliases),
                   publication=Publication(title="P", year=year) if year else None,
                   content=GuidelineContent(applies_to=applies_to, branches=[Branch(name=b) for b in branches]),
                   sources=[], chunks=[])
    if status != "draft":
        row.status = status
        db.commit()
    return row


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


async def test_new_candidate_becomes_new_key(db_session, monkeypatch):
    async def call(prompt):
        return _raw(u1=[_sys("Fleischner")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match_other(db_session, "CT chest", "", U)
    assert [(c.key, c.finding_id, c.branch, c.known) for c in cards] == [("fleischner@2017", "u1", "Subsolid", False)]


async def test_alias_hit_uses_registry_key_branches_and_shows_them(db_session, monkeypatch):
    _put(db_session, "fleischner@2017", "Fleischner", "2017", aliases=["fleischner society"],
         branches=["Solid", "Subsolid nodule"])

    async def call(prompt):
        assert "- fleischner@2017: Fleischner 2017 [branches: Solid | Subsolid nodule]" in prompt
        return _raw(u1=[_sys("Fleischner Society", "2017", branch="subsolid  NODULE")])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match_other(db_session, "CT", "", U[:1])
    assert cards[0].key == "fleischner@2017" and cards[0].known and cards[0].skeleton == ["Solid", "Subsolid nodule"]
    assert cards[0].branch == "Subsolid nodule"          # normalised-equal: the registry's own name


def test_same_branch_is_exact_or_normalised_only():
    assert M._same_branch("Part-solid", ["Solid", "Subsolid"]) == "Part-solid"   # no containment: a new branch
    assert M._same_branch("Subsolid", ["Solid", "Subsolid nodule"]) == "Subsolid"
    assert M._same_branch("solid", ["Solid", "Subsolid"]) == "Solid"
    assert M._same_branch("anything", ["Only"]) == "anything"


async def test_two_versions_go_to_jev(db_session, monkeypatch):
    for v in ("2005", "2017"):
        _put(db_session, f"fleischner@{v}", "Fleischner", v)

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "")])

    async def pick(finding, name, rows, history=""):
        return "fleischner@2005"
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    assert (await M.match_other(db_session, "CT", "", U[:1]))[0].key == "fleischner@2005"


async def test_versionless_no_pick_takes_latest_verified_first(db_session, monkeypatch):
    _put(db_session, "fleischner@2005", "Fleischner", "2005", status="verified")
    _put(db_session, "fleischner@2017", "Fleischner", "2017")
    _put(db_session, "fleischner@2023", "Fleischner", "2023")

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "")])

    async def pick(finding, name, rows, history=""):
        return None
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    cards = await M.match_other(db_session, "CT", "", U[:1])
    assert cards[0].key == "fleischner@2005"             # verified first; never a new unversioned key
    db_session.get(R.GuidelineRegistry, "fleischner@2005").status = "draft"
    db_session.commit()
    M.clear_cache()
    assert (await M.match_other(db_session, "CT", "", U[:1]))[0].key == "fleischner@2023"


async def test_same_version_alias_row_before_jev(db_session, monkeypatch):
    for v in ("2005", "2017"):
        _put(db_session, f"fleischner@{v}", "Fleischner", v, aliases=["fleischner society"])

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner Society", "v2017")])

    async def pick(*a, **k):
        raise AssertionError("same-version alias row must win before Jev")
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    assert (await M.match_other(db_session, "CT", "", U[:1]))[0].key == "fleischner@2017"


def test_version_normalisation():
    assert M._nv("v2019") == M._nv("2019") == "2019"
    assert M._nv("2nd edition") == M._nv("2nd") == "2nd"


async def test_jev_pick_uses_neutral_choice_keys(db_session, monkeypatch):
    rows = [_put(db_session, "fleischner@2005", "Fleischner", "2005", applies_to="Incidental nodules", year="2005"),
            _put(db_session, "fleischner@2017", "Fleischner", "2017", year="2017")]
    seen = {}

    async def jev(payload, key, timeout, transport=None):
        seen.update(payload)
        return _Resp({"answers": {"pick": {"choice": "ed_1", "confidence": 0.9}}})
    monkeypatch.setattr(M, "jev_post", jev)
    assert await M._jev_pick("f", "Fleischner", rows, "hx") == "fleischner@2017"
    crit = seen["questions"]["pick"]["criteria"]
    assert set(crit) == {"ed_0", "ed_1", "none"}
    assert crit["ed_0"] == "Fleischner 2005 — Incidental nodules (2005)"
    assert seen["state"].startswith("CLINICAL HISTORY:\nhx\n\nFINDING:\nf")


async def test_cache_skips_model_for_unchanged_findings(db_session, monkeypatch):
    n = {"calls": 0}

    async def call(prompt):
        n["calls"] += 1
        return _raw(u1=[_sys("Fleischner")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    await M.match_other(db_session, "CT", "", U)
    await M.match_other(db_session, "CT", "", U)
    assert n["calls"] == 1
    await M.match_other(db_session, "CT", "different history", U)   # history is part of the key
    assert n["calls"] == 2


async def test_model_failure_keeps_cached_findings_and_caches_nothing(db_session, monkeypatch):
    async def ok(prompt):
        return _raw(u1=[_sys("Fleischner")])
    monkeypatch.setattr(M, "_call", ok)
    await M.match_other(db_session, "CT", "", U[:1])
    n = {"calls": 0}

    async def down(prompt):
        n["calls"] += 1
        raise RuntimeError("down")
    monkeypatch.setattr(M, "_call", down)
    cards = await M.match_other(db_session, "CT", "", U)
    assert [c.finding_id for c in cards] == ["u1"]       # the cached finding's card survives
    await M.match_other(db_session, "CT", "", U)
    assert n["calls"] == 2                                # the failure cached nothing for u2


async def test_returned_ids_are_normalised(db_session, monkeypatch):
    async def call(prompt):
        return M.RawMatch(findings=[M.RawFinding(id=" [u1] ", systems=[_sys("Fleischner")])])
    monkeypatch.setattr(M, "_call", call)
    assert [c.finding_id for c in await M.match_other(db_session, "CT", "", U[:1])] == ["u1"]


async def test_no_ids_back_caches_nothing(db_session, monkeypatch):
    n = {"calls": 0}

    async def call(prompt):
        n["calls"] += 1
        return M.RawMatch(findings=[M.RawFinding(id="finding-1", systems=[_sys("Fleischner")])])
    monkeypatch.setattr(M, "_call", call)
    assert await M.match_other(db_session, "CT", "", U[:1]) == []
    await M.match_other(db_session, "CT", "", U[:1])
    assert n["calls"] == 2


async def test_caps(db_session, monkeypatch):
    many = [M.Finding(id=f"u{i}", text=f"finding {i}") for i in range(5)]

    async def call(prompt):
        return _raw(**{f.id: [_sys(f"Sys{f.id}a"), _sys(f"Sys{f.id}b"), _sys(f"Sys{f.id}c")] for f in many})
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match_other(db_session, "CT", "", many)
    assert len(cards) == M.MAX_PER_CASE
    assert max(sum(c.finding_id == f.id for c in cards) for f in many) <= M.MAX_PER_FINDING


async def test_caps_take_every_first_before_any_second(db_session, monkeypatch):
    many = [M.Finding(id=f"u{i}", text=f"finding {i}") for i in range(4)]
    monkeypatch.setattr(M, "MAX_PER_CASE", 5)

    async def call(prompt):
        return _raw(**{f.id: [_sys(f"Sys{f.id}a"), _sys(f"Sys{f.id}b")] for f in many})
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match_other(db_session, "CT", "", many)
    assert [c.name for c in cards] == ["Sysu0a", "Sysu1a", "Sysu2a", "Sysu3a", "Sysu0b"]


async def test_tnm_candidate_needs_listed_site_and_jev_gate(db_session, monkeypatch):
    async def call(prompt):
        assert "TNM SITES:" in prompt and "- Lung" in prompt
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site="Lung", why="primary lung mass")],
                    u2=[M.RawSystem(name="TNM", version="9", site="Lungs", why="not on the list")])
    gate = {"Lung": 0.9}

    async def tnm_gate(finding, site, history=""):
        return gate[site]
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    cards = await M.match_other(db_session, "CT", "", U)
    assert [(c.key, c.status, c.branch) for c in cards] == [("tnm-lung@9", "verified", "Staging")]
    M.clear_cache()
    gate["Lung"] = 0.2
    assert await M.match_other(db_session, "CT", "", U) == []


async def test_tnm_site_is_normalised_to_the_closed_list(db_session, monkeypatch):
    async def call(prompt):
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site=" lung ", why="w")])

    async def tnm_gate(finding, site, history=""):
        assert site == "Lung"
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    assert [c.key for c in await M.match_other(db_session, "CT", "", U[:1])] == ["tnm-lung@9"]


async def test_tnm_gate_success_is_cached_failure_is_not(db_session, monkeypatch):
    async def call(prompt):
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site="Lung", why="w")])
    n = {"calls": 0, "fail": True}

    async def tnm_gate(finding, site, history=""):
        n["calls"] += 1
        if n["fail"]:
            raise TimeoutError("jev slow")
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    assert await M.match_other(db_session, "CT", "", U[:1]) == []          # fails closed
    n["fail"] = False
    assert len(await M.match_other(db_session, "MR", "", U[:1])) == 1      # the failure was not cached
    assert len(await M.match_other(db_session, "US", "", U[:1])) == 1      # the success was
    assert n["calls"] == 2


async def test_tnm_gate_state_carries_history(monkeypatch):
    seen = {}

    async def jev(payload, key, timeout, transport=None):
        seen.update(payload)
        return _Resp({"answers": {"q": {"noul": 0.8}}})
    monkeypatch.setattr(M, "jev_post", jev)
    assert await M._tnm_gate("mass", "Lung", "smoker") == 0.8
    assert seen["state"] == "CLINICAL HISTORY:\nsmoker\n\nFINDING:\nmass"


async def test_known_rows_verified_first_and_capped(db_session, monkeypatch):
    _put(db_session, "a-sys@1", "A sys", "1")
    _put(db_session, "b-sys@1", "B sys", "1", status="verified")
    monkeypatch.setattr(M, "KNOWN_MAX", 1)

    async def call(prompt):
        assert "b-sys@1" in prompt and "a-sys@1" not in prompt
        return _raw(u1=[])
    monkeypatch.setattr(M, "_call", call)
    assert await M.match_other(db_session, "CT", "", U[:1]) == []


async def test_model_failure_returns_no_cards(db_session, monkeypatch):
    async def call(prompt):
        raise RuntimeError("down")
    monkeypatch.setattr(M, "_call", call)
    assert await M.match_other(db_session, "CT", "", U) == []


async def test_both_sides_of_the_id_comparison_are_normalised(db_session, monkeypatch):
    async def call(prompt):
        return M.RawMatch(findings=[M.RawFinding(id="u1", systems=[_sys("Fleischner")])])
    monkeypatch.setattr(M, "_call", call)
    f = [M.Finding(id=" [u1] ", text="8 mm part-solid nodule right upper lobe.")]
    assert [c.key for c in await M.match_other(db_session, "CT", "", f)] == ["fleischner@2017"]


async def test_malformed_tnm_gate_answer_fails_closed_and_is_not_cached(db_session, monkeypatch):
    async def call(prompt):
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site="Lung", why="w")])
    st = {"body": {"answers": {}}}

    async def jev(payload, key, timeout, transport=None):
        return _Resp(st["body"])
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "jev_post", jev)
    assert await M.match_other(db_session, "CT", "", U[:1]) == []
    assert len(M._GATE) == 0
    st["body"] = {"answers": {"q": {"noul": 0.9}}}
    assert len(await M.match_other(db_session, "MR", "", U[:1])) == 1


async def test_malformed_edition_pick_is_not_cached(db_session, monkeypatch):
    for v in ("2005", "2017"):
        _put(db_session, f"fleischner@{v}", "Fleischner", v)

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "")])

    async def jev(payload, key, timeout, transport=None):
        return _Resp({"answers": {"pick": {"choice": "ed_0"}}})   # no confidence
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "jev_post", jev)
    assert (await M.match_other(db_session, "CT", "", U[:1]))[0].key == "fleischner@2017"   # latest, no pick
    assert len(M._PICK) == 0


async def test_pick_cache_key_includes_history(db_session, monkeypatch):
    for v in ("2005", "2017"):
        _put(db_session, f"fleischner@{v}", "Fleischner", v)
    seen = []

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "")])

    async def pick(finding, name, rows, history=""):
        seen.append(history)
        return "fleischner@2005"
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    await M.match_other(db_session, "CT", "smoker", U[:1])
    await M.match_other(db_session, "CT", "never smoked", U[:1])
    assert seen == ["smoker", "never smoked"]


async def test_unmatched_branch_goes_to_jev_among_registry_branches(db_session, monkeypatch):
    _put(db_session, "fleischner@2017", "Fleischner", "2017", branches=["Solid", "Subsolid"])
    seen = []

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "2017", branch="Part-solid")])

    async def jev(payload, key, timeout, transport=None):
        seen.append(payload)
        return _Resp({"answers": {"branch": {"choice": "br_1", "confidence": 0.9}}})
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "jev_post", jev)
    cards = await M.match_other(db_session, "CT", "", U[:1])
    assert cards[0].branch == "Subsolid"
    q = seen[0]["questions"]["branch"]
    assert set(q["criteria"]) == {"br_0", "br_1", "none"} and q["criteria"]["br_1"] == "Subsolid"
    assert seen[0]["state"] == f"FINDING:\n{U[0].text}\n\nMODEL BRANCH: Part-solid"
    M._CACHE.clear()
    await M.match_other(db_session, "CT", "", U[:1])
    assert len(seen) == 1                                 # the success was cached


async def test_branch_jev_none_or_failure_keeps_the_model_name(db_session, monkeypatch):
    _put(db_session, "fleischner@2017", "Fleischner", "2017", branches=["Solid", "Subsolid"])
    st = {"body": {"answers": {"branch": {"choice": "none", "confidence": 0.9}}}, "calls": 0}

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "2017", branch="Part-solid")])

    async def jev(payload, key, timeout, transport=None):
        st["calls"] += 1
        if st["body"] is None:
            raise TimeoutError("jev slow")
        return _Resp(st["body"])
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "jev_post", jev)
    assert (await M.match_other(db_session, "CT", "", U[:1]))[0].branch == "Part-solid"
    M.clear_cache()
    st["body"] = None
    assert (await M.match_other(db_session, "CT", "", U[:1]))[0].branch == "Part-solid"
    assert len(M._BRANCH) == 0                            # the failure was not cached


async def test_card_for_reuses_registry_normalisation(db_session):
    _put(db_session, "fleischner@2017", "Fleischner", "2017", aliases=["fleischner society"], branches=["Solid"])
    c = await M.card_for(db_session, "Fleischner Society", "2017", "u1", "7 mm solid nodule.")
    assert (c.key, c.known, c.finding_id) == ("fleischner@2017", True, "u1")
    new = await M.card_for(db_session, "Bosniak", "2019", "q", "cyst")
    assert (new.key, new.known, new.status) == ("bosniak@2019", False, "new")
    assert await M.card_for(db_session, "  ", "", "q", "x") is None


async def test_card_for_tnm_uses_closed_list_and_gate(db_session, monkeypatch):
    gate = {"score": 0.9}

    async def tnm_gate(finding, site, history=""):
        return gate["score"]
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    c = await M.card_for(db_session, "TNM", "9", "u1", "Spiculated lung mass.", site="lung")
    assert c.key == "tnm-lung@9" and c.branch == "Staging"
    assert await M.card_for(db_session, "TNM", "9", "u1", "x", site="Lungs") is None
    M.clear_cache()
    gate["score"] = 0.1
    assert await M.card_for(db_session, "TNM", "9", "u1", "Spiculated lung mass.", site="Lung") is None


async def test_card_for_failure_is_none(db_session, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(M, "_card", boom)
    assert await M.card_for(db_session, "Fleischner", "2017", "u1", "x") is None


async def test_card_for_tnm_without_gate_skips_jev_but_keeps_closed_list(db_session, monkeypatch):
    async def tnm_gate(finding, site, history=""):
        raise AssertionError("no gate for an explicit staging question")
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    c = await M.card_for(db_session, "TNM", "9", "q", "How is this staged?", site="Lung", gate=False)
    assert c.key == "tnm-lung@9"
    assert await M.card_for(db_session, "TNM", "9", "q", "x", site="Lungs", gate=False) is None


def _checked_entry(checked, other=()):
    return Entry(key="fleischner@2017", name="Fleischner", version="2017", content=GuidelineContent(
        branches=[Branch(name=b, state="checked") for b in checked] + [Branch(name=b, state=st) for b, st in other]))


async def test_pick_branch_offers_checked_branches_only(monkeypatch):
    seen = []

    async def post(payload, key, timeout, transport=None):
        seen.append(payload)
        return _Resp({"answers": {"branch": {"choice": "br_0", "confidence": 0.9}}})
    monkeypatch.setattr(M, "jev_post", post)
    entry = _checked_entry(["Subsolid"], [("Solid", "pending"), ("Mass", "not_available")])
    assert await M.pick_branch("part-solid nodule.", entry) == "Subsolid"
    crit = seen[0]["questions"]["branch"]["criteria"]
    assert set(crit) == {"br_0", "none"} and crit["br_0"] == "Subsolid"
    nothing = _checked_entry([], [("Solid", "pending")])
    assert await M.pick_branch("part-solid nodule.", nothing) is None and len(seen) == 1   # no Jev call


async def test_pick_branch_asks_jev_without_a_model_branch_and_caches(db_session, monkeypatch):
    entry = _checked_entry(["Solid", "Subsolid"])
    seen = []

    async def post(payload, key, timeout, transport=None):
        seen.append(payload)
        return _Resp({"answers": {"branch": {"choice": "br_1", "confidence": 0.9}}})
    monkeypatch.setattr(M, "jev_post", post)
    assert await M.pick_branch("8 mm part-solid nodule.", entry, "smoker") == "Subsolid"
    assert await M.pick_branch("8 mm part-solid nodule.", entry, "smoker") == "Subsolid"
    assert len(seen) == 1 and "MODEL BRANCH" not in seen[0]["state"] and "smoker" in seen[0]["state"]
    assert set(seen[0]["questions"]["branch"]["criteria"]) == {"br_0", "br_1", "none"}


async def test_pick_branch_failure_is_none_and_not_cached(db_session, monkeypatch):
    entry = _checked_entry(["Solid"])
    n = {"calls": 0}

    async def post(payload, key, timeout, transport=None):
        n["calls"] += 1
        return _Resp({})
    monkeypatch.setattr(M, "jev_post", post)
    assert await M.pick_branch("x", entry) is None
    assert await M.pick_branch("x", entry) is None and n["calls"] == 2


async def test_match_releases_the_connection_before_the_model(db_session, monkeypatch):
    _put(db_session, "fleischner@2017", "Fleischner", "2017", branches=["Solid"])
    seen = []

    async def call(prompt):
        seen.append(db_session.in_transaction())
        return _raw(u1=[_sys("Fleischner", branch="Solid")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match_other(db_session, "CT chest", "", U)
    assert seen == [False] and cards[0].key == "fleischner@2017" and cards[0].known


from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L


def _toy_lib(toy, *extra):
    entries = {f"{e['id']}@{e['version']}": {"entry": e, "sources": []} for e in (toy, *extra)}
    return L.Library({"version": "v1", "entries": entries})


async def test_a_library_pack_hit_becomes_a_pack_card(db_session, monkeypatch, toy):
    sib = {**toy, "id": "toy-other", "issuer": "OTHER", "display": "Other 2021", "aliases": ["other nodule"]}
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy, sib))

    async def call(prompt):
        assert "- toy-nodule@1.0: Toy 2020 [aliases: toy nodule | toy guideline]" in prompt
        return _raw(u1=[_sys("Toy Nodule", "2020")])

    async def pack_gate(finding, pack, history=""):
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    cards = await M.match_other(db_session, "CT chest", "", U[:1])
    assert [(c.key, c.branch, c.skeleton, c.status, c.known, c.siblings) for c in cards] == \
        [("toy-nodule@1.0", "Pack", ["Pack"], "verified", True, ["toy-other@1.0"])]


def _pack_match(monkeypatch, toy):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy))

    async def call(prompt):
        return _raw(u1=[_sys("Toy Nodule", "2020")])
    monkeypatch.setattr(M, "_call", call)


async def test_pack_card_needs_the_jev_applicability_gate(db_session, monkeypatch, toy):
    _pack_match(monkeypatch, toy)
    gate = {"score": 0.9}

    async def pack_gate(finding, pack, history=""):
        assert pack.key == "toy-nodule@1.0" and history == "smoker"
        return gate["score"]
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    assert [c.key for c in await M.match_other(db_session, "CT", "smoker", U[:1])] == ["toy-nodule@1.0"]
    M.clear_cache()
    gate["score"] = M.PACK_GATE_MIN - 0.01
    assert await M.match_other(db_session, "CT", "smoker", U[:1]) == []   # no card, and no fall-through to a registry key


async def test_pack_gate_jev_failure_is_no_card(db_session, monkeypatch, toy):
    _pack_match(monkeypatch, toy)

    async def jev(payload, key, timeout, transport=None):
        raise TimeoutError("jev slow")
    monkeypatch.setattr(M, "jev_post", jev)
    assert await M.match_other(db_session, "CT", "", U[:1]) == []
    assert len(M._GATE) == 0


async def test_pack_gate_success_is_cached_failure_is_not(db_session, monkeypatch, toy):
    _pack_match(monkeypatch, toy)
    n = {"calls": 0, "fail": True}

    async def pack_gate(finding, pack, history=""):
        n["calls"] += 1
        if n["fail"]:
            raise TimeoutError("jev slow")
        return 0.9
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    assert await M.match_other(db_session, "CT", "", U[:1]) == []          # fails closed
    n["fail"] = False
    assert len(await M.match_other(db_session, "MR", "", U[:1])) == 1      # the failure was not cached
    assert len(await M.match_other(db_session, "US", "", U[:1])) == 1      # the success was
    assert n["calls"] == 2


async def test_pack_gate_asks_a_case_agnostic_question_with_history(monkeypatch, toy_entry):
    seen = {}

    async def jev(payload, key, timeout, transport=None):
        seen.update(payload)
        return _Resp({"answers": {"q": {"noul": 0.8}}})
    monkeypatch.setattr(M, "jev_post", jev)
    assert await M._pack_gate("nodule", toy_entry, "smoker") == 0.8
    assert seen["state"] == "CLINICAL HISTORY:\nsmoker\n\nFINDING:\nnodule"
    assert seen["questions"]["q"] == {"type": "noul", "instructions":
                                      "The FINDING describes an incidental nodule of the chest that Toy 2020 applies to."}


async def test_card_for_pack_without_gate_skips_jev(db_session, monkeypatch, toy):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy))

    async def pack_gate(finding, pack, history=""):
        raise AssertionError("gate=False skips the pack gate")
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    c = await M.card_for(db_session, "Toy Nodule", "2020", "q", "x", gate=False)
    assert c.key == "toy-nodule@1.0"


async def test_a_reference_entry_hit_becomes_a_read_only_card(db_session, monkeypatch, toy, toy_reference):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy, toy_reference))

    async def call(prompt):
        assert "- toy-grade@1.0: Toy grade 2020 [aliases: toy grade]" in prompt
        return _raw(u1=[_sys("Toy grade", "2020")])
    gated = []

    async def pack_gate(finding, pack, history=""):
        gated.append(pack.key)
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    cards = await M.match_other(db_session, "MRI knee", "", U[:1])
    assert [(c.key, c.branch, c.skeleton, c.reference) for c in cards] == \
        [("toy-grade@1.0", "Reference", ["Reference"], True)]
    assert gated == ["toy-grade@1.0"]


async def test_a_library_card_carries_its_finding_text(db_session, monkeypatch, toy):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy))

    async def call(prompt):
        return _raw(u1=[_sys("Toy Nodule", "2020")])

    async def pack_gate(finding, pack, history=""):
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    cards = await M.match_other(db_session, "CT chest", "", U[:1])
    assert [(c.key, c.finding) for c in cards] == [("toy-nodule@1.0", U[0].text)]


def _keyed(key, name="", version=""):
    return M.RawSystem(key=key, name=name, version=version, why="w")


async def test_a_listed_key_resolves_the_pack_without_name_matching_and_is_still_gated(db_session, monkeypatch, toy):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy))
    gate = {"score": 0.9, "seen": []}

    async def pgate(finding, pack, history):
        gate["seen"].append(pack.key)
        return gate["score"]
    monkeypatch.setattr(M, "_pgate", pgate)
    rows = M._Rows(db_session)
    f = M.Finding(id="u1", text="nodule")
    for s in (_keyed("toy-nodule@1.0", "A name no pack has"), _keyed("toy-nodule@1.0")):
        c = await M._card(rows, f, s, "")
        assert (c.key, c.name, c.version) == ("toy-nodule@1.0", "Toy 2020", "2020")
    assert gate["seen"] == ["toy-nodule@1.0", "toy-nodule@1.0"]
    gate["score"] = M.PACK_GATE_MIN - 0.01
    assert await M._card(rows, f, _keyed("toy-nodule@1.0", "Toy Nodule"), "") is None   # gated: no fall-through


async def test_an_unknown_or_superseded_key_falls_back_to_the_name(db_session, monkeypatch, toy):
    old = {**toy, "version": "0.9", "status": "superseded"}
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy, old))

    async def pgate(finding, pack, history):
        return 0.9
    monkeypatch.setattr(M, "_pgate", pgate)
    monkeypatch.setattr(R, "web_fetch_on", lambda: False)
    rows, f = M._Rows(db_session), M.Finding(id="u1", text="nodule")
    assert (await M._card(rows, f, _keyed("nope@1.0", "Toy Nodule"), "")).key == "toy-nodule@1.0"
    assert (await M._card(rows, f, _keyed("toy-nodule@0.9", "Toy Nodule"), "")).key == "toy-nodule@1.0"
    assert await M._card(rows, f, _keyed("nope@1.0"), "") is None   # no key hit, no name: nothing


async def test_the_prompt_lists_library_keys_with_scope_and_asks_for_the_key(db_session, monkeypatch, toy):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy))
    seen = []

    async def call(prompt):
        seen.append(prompt)
        return _raw(u1=[_keyed("toy-nodule@1.0")])

    async def pack_gate(finding, pack, history=""):
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    cards = await M.match_other(db_session, "CT chest", "", U[:1])
    assert "KNOWN SYSTEMS" in seen[0]
    assert "- toy-nodule@1.0: Toy 2020 [aliases: toy nodule | toy guideline] (scope: nodule in chest" in seen[0]
    assert "key:" in M.MATCH_SYS and "scope" in M.MATCH_SYS
    assert [c.key for c in cards] == ["toy-nodule@1.0"]
