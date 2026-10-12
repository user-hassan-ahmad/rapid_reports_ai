from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, GuidelineContent

U = [M.Finding(id="u1", text="8 mm part-solid nodule right upper lobe."), M.Finding(id="u2", text="Simple renal cyst.")]


def _raw(**per):
    return M.RawMatch(findings=[M.RawFinding(id=k, systems=v) for k, v in per.items()])


def _sys(name, version="2017", branch="Subsolid", skeleton=("Solid", "Subsolid")):
    return M.RawSystem(name=name, version=version, why="w", branch=branch, skeleton=list(skeleton),
                       publication=M.Publication(title="T", year=version))


async def test_new_candidate_becomes_new_key(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT chest", "", U)
    assert [(c.key, c.finding_id, c.branch, c.known) for c in cards] == [("fleischner@2017", "u1", "Subsolid", False)]


async def test_alias_hit_uses_registry_key_and_branches(db_session, monkeypatch):
    M.clear_cache()
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=["fleischner society"],
             publication=None, content=GuidelineContent(branches=[Branch(name="Solid"), Branch(name="Subsolid nodule")]),
             sources=[], chunks=[])

    async def call(prompt):
        assert "fleischner@2017" in prompt          # the known registry names are offered
        return _raw(u1=[_sys("Fleischner Society", "2017")])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", U[:1])
    assert cards[0].key == "fleischner@2017" and cards[0].known and cards[0].skeleton == ["Solid", "Subsolid nodule"]
    assert cards[0].branch == "Subsolid nodule"          # the registry's branch name, not the model's


def test_same_branch_matches_whole_words_not_substrings():
    sk = ["Solid", "Subsolid nodule"]
    assert M._same_branch("Subsolid", sk) == "Subsolid nodule"   # "solid" is inside "subsolid", but not a word of it
    assert M._same_branch("solid", sk) == "Solid"
    assert M._same_branch("Cystic", sk) == "Cystic"              # a new branch keeps the model's name
    assert M._same_branch("anything", ["Only"]) == "Only"


async def test_two_versions_go_to_jev(db_session, monkeypatch):
    M.clear_cache()
    for v in ("2005", "2017"):
        R.upsert(db_session, key=f"fleischner@{v}", name="Fleischner", version=v, aliases=[], publication=None,
                 content=GuidelineContent(), sources=[], chunks=[])

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "")])

    async def pick(finding, name, rows):
        return "fleischner@2017"
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    assert (await M.match(db_session, "CT", "", U[:1]))[0].key == "fleischner@2017"


async def test_cache_skips_model_for_unchanged_findings(db_session, monkeypatch):
    M.clear_cache()
    n = {"calls": 0}

    async def call(prompt):
        n["calls"] += 1
        return _raw(u1=[_sys("Fleischner")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    await M.match(db_session, "CT", "", U)
    await M.match(db_session, "CT", "", U)
    assert n["calls"] == 1


async def test_caps(db_session, monkeypatch):
    M.clear_cache()
    many = [M.Finding(id=f"u{i}", text=f"finding {i}") for i in range(5)]

    async def call(prompt):
        return _raw(**{f.id: [_sys(f"Sys{f.id}a"), _sys(f"Sys{f.id}b"), _sys(f"Sys{f.id}c")] for f in many})
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", many)
    assert len(cards) == M.MAX_PER_CASE
    assert max(sum(c.finding_id == f.id for c in cards) for f in many) <= M.MAX_PER_FINDING


async def test_tnm_candidate_needs_listed_site_and_jev_gate(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        assert "TNM SITES:" in prompt and "- Lung" in prompt
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site="Lung", why="primary lung mass")],
                    u2=[M.RawSystem(name="TNM", version="9", site="Lungs", why="not on the list")])
    gate = {"Lung": 0.9}

    async def tnm_gate(finding, site):
        return gate[site]
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    cards = await M.match(db_session, "CT", "", U)
    assert [(c.key, c.status, c.branch) for c in cards] == [("tnm-lung@9", "verified", "Staging")]
    M.clear_cache()
    gate["Lung"] = 0.2
    assert await M.match(db_session, "CT", "", U) == []


async def test_tnm_gate_failure_fails_closed(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site="Lung", why="w")])

    async def tnm_gate(finding, site):
        raise TimeoutError("jev slow")
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    assert await M.match(db_session, "CT", "", U[:1]) == []


async def test_model_failure_returns_no_cards(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        raise RuntimeError("down")
    monkeypatch.setattr(M, "_call", call)
    assert await M.match(db_session, "CT", "", U) == []
