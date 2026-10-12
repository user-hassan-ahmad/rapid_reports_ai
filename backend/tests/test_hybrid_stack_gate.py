import json

import httpx

from rapid_reports_ai.hybrid_stack import gate
from rapid_reports_ai.hybrid_stack.units import StackUnit


def _jev(answers: list[tuple[str, float]], seen: list):
    it = iter(answers)

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        choice, conf = next(it)
        return httpx.Response(200, json={"answers": {"boundary": {"choice": choice, "confidence": conf}}})
    return httpx.MockTransport(handler)


def _u(i, text, group, **kw):
    return StackUnit(id=i, text=text, group=group, **kw)


async def test_gate_asks_only_after_conclusion_and_moves_confident_summary(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []
    units = [_u(0, "A lesion.", "Liver"), _u(1, "Impression, cancer.", "Conclusion"),
             _u(2, "Lesion is cancer.", "Liver", attach_to=0)]
    log = await gate.conclusion_gate(units, [2], transport=_jev([("summary", 0.9)], seen))
    assert units[2].group == "Conclusion" and units[2].attach_to is None
    assert len(seen) == 1 and "SENTENCE:\nLesion is cancer." in seen[0]["state"]
    assert log[0]["to"] == "Conclusion"


async def test_low_confidence_keeps_grouper_placement(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Impression, x.", "Conclusion"), _u(1, "Liver lesion 2 cm.", "Liver")]
    await gate.conclusion_gate(units, [1], transport=_jev([("summary", 0.4)], []))
    assert units[1].group == "Liver"


async def test_images_moves_out_of_conclusion(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "In summary, x.", "Conclusion"), _u(1, "Also a renal cyst.", "Conclusion")]
    await gate.conclusion_gate(units, [1], transport=_jev([("images", 0.8)], []))
    assert units[1].group == "General"


async def test_no_conclusion_no_call_and_pinned_skipped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []
    units = [_u(0, "A.", "Liver"), _u(1, "B.", "Liver", pinned=True)]
    assert await gate.conclusion_gate(units, [1], transport=_jev([], seen)) == [] and seen == []


async def test_closing_check_moves_uncued_summary_last_line(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Segment 8 lesion with washout.", "Liver"),
             _u(1, "Observation is LI-RADS 5, consistent with HCC.", "Liver")]
    log = await gate.closing_check(units, transport=_jev([("summary", 0.8)], []))
    assert units[1].group == "Conclusion" and log["to"] == "Conclusion"


async def test_closing_check_skips_when_a_conclusion_exists(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Impression, x.", "Conclusion"), _u(1, "Y.", "Conclusion")]
    assert await gate.closing_check(units, transport=_jev([], [])) is None


async def test_failure_fails_open(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Impression, x.", "Conclusion"), _u(1, "Liver lesion.", "Liver")]
    log = await gate.conclusion_gate(units, [1], transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert units[1].group == "Liver" and log[0]["choice"].startswith("error")
