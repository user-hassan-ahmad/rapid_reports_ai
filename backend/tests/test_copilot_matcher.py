import pytest

from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, GuidelineContent, Publication

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
    cards = await M.match(db_session, "CT chest", "", U)
    assert [(c.key, c.finding_id, c.branch, c.known) for c in cards] == [("fleischner@2017", "u1", "Subsolid", False)]


async def test_alias_hit_uses_registry_key_branches_and_shows_them(db_session, monkeypatch):
    _put(db_session, "fleischner@2017", "Fleischner", "2017", aliases=["fleischner society"],
         branches=["Solid", "Subsolid nodule"])

    async def call(prompt):
        assert "- fleischner@2017: Fleischner 2017 [branches: Solid | Subsolid nodule]" in prompt
        return _raw(u1=[_sys("Fleischner Society", "2017", branch="subsolid  NODULE")])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", U[:1])
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
    assert (await M.match(db_session, "CT", "", U[:1]))[0].key == "fleischner@2005"


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
    cards = await M.match(db_session, "CT", "", U[:1])
    assert cards[0].key == "fleischner@2005"             # verified first; never a new unversioned key
    db_session.get(R.GuidelineRegistry, "fleischner@2005").status = "draft"
    db_session.commit()
    M.clear_cache()
    assert (await M.match(db_session, "CT", "", U[:1]))[0].key == "fleischner@2023"


async def test_same_version_alias_row_before_jev(db_session, monkeypatch):
    for v in ("2005", "2017"):
        _put(db_session, f"fleischner@{v}", "Fleischner", v, aliases=["fleischner society"])

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner Society", "v2017")])

    async def pick(*a, **k):
        raise AssertionError("same-version alias row must win before Jev")
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    assert (await M.match(db_session, "CT", "", U[:1]))[0].key == "fleischner@2017"


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
    await M.match(db_session, "CT", "", U)
    await M.match(db_session, "CT", "", U)
    assert n["calls"] == 1
    await M.match(db_session, "CT", "different history", U)   # history is part of the key
    assert n["calls"] == 2


async def test_model_failure_keeps_cached_findings_and_caches_nothing(db_session, monkeypatch):
    async def ok(prompt):
        return _raw(u1=[_sys("Fleischner")])
    monkeypatch.setattr(M, "_call", ok)
    await M.match(db_session, "CT", "", U[:1])
    n = {"calls": 0}

    async def down(prompt):
        n["calls"] += 1
        raise RuntimeError("down")
    monkeypatch.setattr(M, "_call", down)
    cards = await M.match(db_session, "CT", "", U)
    assert [c.finding_id for c in cards] == ["u1"]       # the cached finding's card survives
    await M.match(db_session, "CT", "", U)
    assert n["calls"] == 2                                # the failure cached nothing for u2


async def test_returned_ids_are_normalised(db_session, monkeypatch):
    async def call(prompt):
        return M.RawMatch(findings=[M.RawFinding(id=" [u1] ", systems=[_sys("Fleischner")])])
    monkeypatch.setattr(M, "_call", call)
    assert [c.finding_id for c in await M.match(db_session, "CT", "", U[:1])] == ["u1"]


async def test_no_ids_back_caches_nothing(db_session, monkeypatch):
    n = {"calls": 0}

    async def call(prompt):
        n["calls"] += 1
        return M.RawMatch(findings=[M.RawFinding(id="finding-1", systems=[_sys("Fleischner")])])
    monkeypatch.setattr(M, "_call", call)
    assert await M.match(db_session, "CT", "", U[:1]) == []
    await M.match(db_session, "CT", "", U[:1])
    assert n["calls"] == 2


async def test_caps(db_session, monkeypatch):
    many = [M.Finding(id=f"u{i}", text=f"finding {i}") for i in range(5)]

    async def call(prompt):
        return _raw(**{f.id: [_sys(f"Sys{f.id}a"), _sys(f"Sys{f.id}b"), _sys(f"Sys{f.id}c")] for f in many})
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", many)
    assert len(cards) == M.MAX_PER_CASE
    assert max(sum(c.finding_id == f.id for c in cards) for f in many) <= M.MAX_PER_FINDING


async def test_caps_take_every_first_before_any_second(db_session, monkeypatch):
    many = [M.Finding(id=f"u{i}", text=f"finding {i}") for i in range(4)]
    monkeypatch.setattr(M, "MAX_PER_CASE", 5)

    async def call(prompt):
        return _raw(**{f.id: [_sys(f"Sys{f.id}a"), _sys(f"Sys{f.id}b")] for f in many})
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", many)
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
    cards = await M.match(db_session, "CT", "", U)
    assert [(c.key, c.status, c.branch) for c in cards] == [("tnm-lung@9", "verified", "Staging")]
    M.clear_cache()
    gate["Lung"] = 0.2
    assert await M.match(db_session, "CT", "", U) == []


async def test_tnm_site_is_normalised_to_the_closed_list(db_session, monkeypatch):
    async def call(prompt):
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site=" lung ", why="w")])

    async def tnm_gate(finding, site, history=""):
        assert site == "Lung"
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    assert [c.key for c in await M.match(db_session, "CT", "", U[:1])] == ["tnm-lung@9"]


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
    assert await M.match(db_session, "CT", "", U[:1]) == []          # fails closed
    n["fail"] = False
    assert len(await M.match(db_session, "MR", "", U[:1])) == 1      # the failure was not cached
    assert len(await M.match(db_session, "US", "", U[:1])) == 1      # the success was
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
    assert await M.match(db_session, "CT", "", U[:1]) == []


async def test_model_failure_returns_no_cards(db_session, monkeypatch):
    async def call(prompt):
        raise RuntimeError("down")
    monkeypatch.setattr(M, "_call", call)
    assert await M.match(db_session, "CT", "", U) == []
