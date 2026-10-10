import json

import httpx

from rapid_reports_ai.hybrid_stack import grouper as G
from rapid_reports_ai.hybrid_stack.grouper import Part, Placement, apply_placements, valid_parts
from rapid_reports_ai.hybrid_stack.schemas import Region
from rapid_reports_ai.hybrid_stack.units import StackUnit

GROUPS = ["Technique", "Liver", "Kidneys", "Other findings", "General", "Conclusion"]


def _units(*texts):
    return [StackUnit(id=i, text=t) for i, t in enumerate(texts)]


def test_parts_must_cover_the_sentence_exactly():
    s = "Kidneys are normal, and there is a 3 cm liver cyst."
    assert valid_parts(s, [Part(text="Kidneys are normal,", group="Kidneys"),
                           Part(text="and there is a 3 cm liver cyst.", group="Liver")])
    assert not valid_parts(s, [Part(text="Kidneys are normal", group="Kidneys"),
                               Part(text="there is a 3 cm liver cyst.", group="Liver")])  # ", and" dropped
    assert not valid_parts(s, [Part(text=s, group="Kidneys")])  # one part is not a split


def test_attached_sentence_takes_parent_group_and_covers_are_filtered():
    units = _units("A liver lesion.", "It measures 2 cm.")
    problems = apply_placements(units, [
        Placement(id=0, group="Liver", structure="liver", covers=["Liver", "General", "Nope"]),
        Placement(id=1, group="Kidneys", attach_to=0, covers=["Liver"]),
    ], [0, 1], GROUPS)
    assert units[0].covers == ["Liver"]
    assert units[1].group == "Liver" and units[1].attach_to == 0
    assert problems == []


def test_unknown_group_and_missing_placement_go_to_general():
    units = _units("One.", "Two.")
    problems = apply_placements(units, [Placement(id=0, group="Spleen")], [0, 1], GROUPS)
    assert units[0].group == "General" and units[1].group == "General"
    assert len(problems) == 2


def test_forward_or_self_link_is_cut():
    units = _units("One.", "Two.")
    apply_placements(units, [Placement(id=0, group="Liver", attach_to=1), Placement(id=1, group="Liver", attach_to=1)],
                     [0, 1], GROUPS)
    assert units[0].attach_to is None and units[1].attach_to is None


def test_split_into_one_group_is_not_a_split():
    units = _units("Liver and spleen normal.")
    apply_placements(units, [Placement(id=0, group="Liver", parts=[Part(text="Liver", group="Liver"),
                                                                   Part(text="and spleen normal.", group="Liver")])],
                     [0], GROUPS)
    assert units[0].parts is None


def test_placements_for_old_or_pinned_units_are_ignored():
    units = [StackUnit(id=0, text="Old.", group="Liver", pinned=True), StackUnit(id=1, text="New.")]
    apply_placements(units, [Placement(id=0, group="Kidneys"), Placement(id=1, group="Kidneys")], [1], GROUPS)
    assert units[0].group == "Liver" and units[1].group == "Kidneys"

REGIONS = [Region(name="Liver", includes="liver"), Region(name="Kidneys", includes="kidneys")]


def _llm(body_out: dict, seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body_out)}}]})
    return httpx.MockTransport(handler)


async def test_place_sends_regions_with_includes_and_only_new_sentences(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    seen = []
    units = [StackUnit(id=0, text="Liver normal.", group="Liver"), StackUnit(id=1, text="Kidneys normal.")]
    out = {"placements": [{"id": 1, "group": "Kidneys", "structure": "kidneys", "covers": ["Kidneys"]}]}
    placements, model, err = await G.place("CT abdomen", REGIONS, units, [1], transport=_llm(out, seen))
    assert err is None and model == "qwen-3.8-27b" and placements[0].group == "Kidneys"
    body = seen[0][1]
    user = body["messages"][1]["content"]
    assert "Liver — includes: liver" in user
    assert "[0] (Liver) Liver normal." in user and "[1] Kidneys normal." in user
    assert body["response_format"]["type"] == "json_schema" and body["reasoning_effort"] == "none"


async def test_place_falls_back_to_groq_then_reports_error(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(500)
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0],
                                           transport=httpx.MockTransport(handler))
    assert placements == [] and model is None and "qwen/qwen3.8-27b" in err
    assert any("cerebras" in c for c in calls) and any("groq" in c for c in calls)


def test_unplaced_parent_falls_back_to_own_group():
    units = [StackUnit(id=0, text="Old."), StackUnit(id=1, text="It is 2 cm.")]
    problems = apply_placements(units, [Placement(id=1, group="Liver", attach_to=0)], [1], GROUPS)
    assert units[1].group == "Liver" and units[1].attach_to == 0
    assert "[1] parent 0 unplaced" in problems


def test_new_ids_are_processed_in_order():
    units = _units("A liver lesion.", "It measures 2 cm.")
    problems = apply_placements(units, [Placement(id=0, group="Liver"), Placement(id=1, group="Kidneys", attach_to=0)],
                                [1, 0], GROUPS)
    assert units[1].group == "Liver" and problems == []


def test_attached_sentence_never_keeps_parts():
    units = _units("A liver lesion.", "Kidneys are normal, and spleen too.")
    parts = [Part(text="Kidneys are normal,", group="Kidneys"), Part(text="and spleen too.", group="Liver")]
    problems = apply_placements(units, [Placement(id=0, group="Liver"),
                                        Placement(id=1, group="Liver", attach_to=0, parts=parts)], [0, 1], GROUPS)
    assert units[1].parts is None and units[1].attach_to == 0
    assert "[1] parts on attached sentence" in problems


def test_parts_cannot_split_inside_a_word_or_be_punctuation_only():
    s = "Kidneys normal, liver cyst."
    assert not valid_parts(s, [Part(text="Kidneys norm", group="Kidneys"), Part(text="al, liver cyst.", group="Liver")])
    assert not valid_parts("B.", [Part(text="B", group="Liver"), Part(text=".", group="Kidneys")])
    assert valid_parts(s, [Part(text="Kidneys normal,", group="Kidneys"), Part(text="liver cyst.", group="Liver")])


def test_accepted_split_takes_first_part_group():
    s = "Kidneys are normal, and there is a liver cyst."
    units = _units(s)
    apply_placements(units, [Placement(id=0, group="Liver", parts=[
        Part(text="Kidneys are normal,", group="kidneys"), Part(text="and there is a liver cyst.", group="Liver")])],
        [0], GROUPS)
    assert [x.group for x in units[0].parts] == ["Kidneys", "Liver"] and units[0].group == "Kidneys"


def test_unknown_new_id_is_logged_not_raised():
    units = _units("One.")
    problems = apply_placements(units, [Placement(id=0, group="Liver")], [0, 5], GROUPS)
    assert units[0].group == "Liver" and any("[5]" in x for x in problems)


async def test_empty_placements_fall_through_to_groq(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = []

    def handler(req):
        seen.append(str(req.url))
        out = {"placements": []} if "cerebras" in str(req.url) else {"placements": [{"id": 0, "group": "Liver"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0],
                                           transport=httpx.MockTransport(handler))
    assert model == "qwen/qwen3.8-27b" and len(placements) == 1 and err is None and len(seen) == 2


async def test_malformed_content_returns_error(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]}))
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0], transport=t)
    assert placements == [] and model is None and "qwen-3.8-27b" in err


async def test_only_groq_key_uses_groq(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = []
    out = {"placements": [{"id": 0, "group": "Liver"}]}
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0], transport=_llm(out, seen))
    assert model == "qwen/qwen3.8-27b" and len(seen) == 1 and "groq" in seen[0][0]


async def test_no_keys_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0])
    assert placements == [] and model is None and err == "no grouper endpoint configured"


def test_placement_field_order_keeps_covers_before_attach_and_parts():
    # Cerebras Qwen decodes fields in schema order; with attach_to/parts before covers every reply ran
    # away to the length limit (6/6 on a lab case) and the grouper silently fell back to Groq.
    assert list(G.Placement.model_fields) == ["id", "group", "structure", "covers", "attach_to", "parts"]


async def test_place_reports_a_runaway_reply(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    def handler(req):
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"placements": [{"id'}}]})
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0],
                                           transport=httpx.MockTransport(handler))
    assert placements == [] and "length" in err
