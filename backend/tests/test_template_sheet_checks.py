import pytest

from rapid_reports_ai import template_sheet_checks as C
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Knee (FINDINGS)
COVERS ["menisci" | "cartilage" | "ligaments"]
NORMAL [menisci] "The menisci are intact."
NORMAL [cartilage] "Mild chondral irregularity and thinning."
NEGATIVE "No effusion, synovitis or loose body."
NORMAL [ligaments] "LVEF {value}%."
"""


def _structure():
    res = parse_sheet(SHEET, mode="template")
    assert res.structure.usable, res.errors
    return res.structure


async def test_checks_flag_placeholders_abnormal_and_multi_structure(monkeypatch):
    async def fake(units):
        return {u.text: (0.1 if "Mild" in u.text else 0.95, 0.9 if "effusion" in u.text else 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    monkeypatch.setattr(C, "MULTI_MIN", 0.6)  # shipped off (no clean gap in the lab); the logic is still tested
    fails = await C.check_units(_structure(), SHEET)
    by = {f.text: f.reason for f in fails}
    assert by["LVEF {value}%."] == C.PLACEHOLDER
    assert by["Mild chondral irregularity and thinning."] == C.NOT_NORMAL
    assert by["No effusion, synovitis or loose body."] == C.MULTI_STRUCTURE
    assert "The menisci are intact." not in by
    lines = SHEET.splitlines()
    for f in fails:
        assert f.line > 0 and lines[f.line - 1] == f.source_line and f.text in f.source_line


async def test_multi_structure_check_is_off_by_default(monkeypatch):
    async def fake(units):
        return {u.text: (0.95, 0.99) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    fails = await C.check_units(_structure(), SHEET)
    assert [f.reason for f in fails] == [C.PLACEHOLDER]


async def test_placeholder_units_are_not_sent_to_jev(monkeypatch):
    seen = []

    async def fake(units):
        seen.extend(u.text for u in units)
        return {u.text: (0.95, 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    await C.check_units(_structure())
    assert "LVEF {value}%." not in seen and len(seen) == 3


async def test_jev_scores_chunks_large_sheets(monkeypatch, keyed):
    calls = []

    class R:
        def __init__(self, n):
            self.n = n

        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": {f"{p}{i}": {"noul": 0.7} for i in range(self.n) for p in "nm"}}

    async def fake_post(body, key, timeout):
        n = sum(k.startswith("n") for k in body["questions"])
        calls.append(n)
        return R(n)

    monkeypatch.setattr(C, "jev_post", fake_post)

    class U:
        def __init__(self, t):
            self.text = t

    out = await C._jev_scores([U(f"Unit {i}.") for i in range(85)])
    assert calls == [40, 40, 5]
    assert len(out) == 85 and out["Unit 84."] == (0.7, 0.0)


async def test_jev_error_raises(monkeypatch):
    async def boom(units):
        raise RuntimeError("jev down")

    monkeypatch.setattr(C, "_jev_scores", boom)
    with pytest.raises(RuntimeError):
        await C.check_units(_structure())


class _Resp:
    def __init__(self, payload, fail=False):
        self.payload, self.fail = payload, fail

    def raise_for_status(self):
        if self.fail:
            raise RuntimeError("http 500")

    def json(self):
        return self.payload


class _U:
    def __init__(self, t):
        self.text = t


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_JEV_ROUTE", raising=False)


def _post_returning(resp, bodies=None):
    async def fake_post(body, key, timeout):
        if bodies is not None:
            bodies.append(body)
        return resp

    return fake_post


async def test_no_answers_raises(monkeypatch, keyed):
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp({})))
    with pytest.raises(ValueError, match="incomplete answers"):
        await C._jev_scores([_U("A."), _U("B.")])


async def test_partial_answers_raise(monkeypatch, keyed):
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp({"answers": {"n0": {"noul": 0.9}}})))
    with pytest.raises(ValueError, match="incomplete answers"):
        await C._jev_scores([_U("A."), _U("B.")])


async def test_non_numeric_answer_raises(monkeypatch, keyed):
    payload = {"answers": {"n0": {"noul": "yes"}}}
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp(payload)))
    with pytest.raises(ValueError, match="incomplete answers"):
        await C._jev_scores([_U("A.")])


async def test_http_error_raises(monkeypatch, keyed):
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp({}, fail=True)))
    with pytest.raises(RuntimeError, match="http 500"):
        await C._jev_scores([_U("A.")])


async def test_no_multi_questions_sent_while_off(monkeypatch, keyed):
    bodies = []
    payload = {"answers": {"n0": {"noul": 0.9}, "n1": {"noul": 0.8}}}
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp(payload), bodies))
    out = await C._jev_scores([_U("A."), _U("B.")])
    assert sorted(bodies[0]["questions"]) == ["n0", "n1"]
    assert out == {"A.": (0.9, 0.0), "B.": (0.8, 0.0)}


async def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RR_JEV_ROUTE", raising=False)
    called = []
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp({}), called))
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY unset"):
        await C._jev_scores([_U("A.")])
    assert called == []


async def test_direct_route_needs_no_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("RR_JEV_ROUTE", "direct")
    monkeypatch.setenv("JEV_API_KEY", "d")
    monkeypatch.setattr(C, "jev_post", _post_returning(_Resp({"answers": {"n0": {"noul": 0.9}}})))
    assert await C._jev_scores([_U("A.")]) == {"A.": (0.9, 0.0)}


async def test_line_is_zero_without_sheet_text(monkeypatch):
    async def fake(units):
        return {u.text: (0.95, 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    fails = await C.check_units(_structure())
    assert [(f.line, f.reason) for f in fails] == [(0, C.PLACEHOLDER)]


async def test_repeated_source_lines_map_to_successive_lines(monkeypatch):
    dup = 'NORMAL [ligaments] "LVEF {value}%."'
    sheet = SHEET.replace("## Paragraph: Knee (FINDINGS)",
                          "## Paragraph: Heart (FINDINGS)\nCOVERS [\"ligaments\"]\n" + dup + "\n\n## Paragraph: Knee (FINDINGS)")
    res = parse_sheet(sheet, mode="template")
    assert res.structure.usable, res.errors

    async def fake(units):
        return {u.text: (0.95, 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    fails = [f for f in await C.check_units(res.structure, sheet) if f.reason == C.PLACEHOLDER]
    lines = sheet.splitlines()
    assert len(fails) == 2 and len({f.line for f in fails}) == 2
    assert all(lines[f.line - 1] == dup for f in fails)


async def test_check_units_runs_on_a_structure_marked_unusable(monkeypatch):
    # the save function checks units of a sheet unusable only through old lint errors (template_sheet_save._usable)
    from tests.template_sheet_fixtures import GOOD
    sheet = GOOD + "COVERS menisci without brackets\n" + 'NORMAL [bone] "The bones are {x}."\n' \
        + 'NORMAL [cartilage] "Mild chondral thinning."\n'
    res = parse_sheet(sheet, mode="template")
    assert not res.structure.usable and res.errors

    async def scores(units):
        return {u.text: (0.05 if "thinning" in u.text else 0.9, 0.0) for u in units}
    monkeypatch.setattr(C, "_jev_scores", scores)
    fails = await C.check_units(res.structure, sheet)
    assert {(f.text, f.reason) for f in fails} == {("The bones are {x}.", C.PLACEHOLDER),
                                                  ("Mild chondral thinning.", C.NOT_NORMAL)}
