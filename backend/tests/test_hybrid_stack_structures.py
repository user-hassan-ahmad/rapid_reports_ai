import json

import httpx
import pytest

from rapid_reports_ai.hybrid_stack import structures
from rapid_reports_ai.hybrid_stack.structures import structure_normals
from rapid_reports_ai.hybrid_stack.template import template_region_normals
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Coronary Arteries (FINDINGS)
COVERS ["CORONARY ARTERIES"]
NORMAL [CORONARY ARTERIES] "Normal coronary arteries."

## Paragraph: Other Findings (FINDINGS)
COVERS ["CARDIAC CHAMBERS" | "LUNGS" | "EFFUSIONS" | "GREAT VESSELS" | "BONES"]
NORMAL [CARDIAC CHAMBERS] "Normal appearance of the cardiac chambers."
NEGATIVE "No suspicious parenchymal nodules."
NEGATIVE "No pleural or pericardial effusion."
NORMAL [GREAT VESSELS] "Normal calibre aortic root and pulmonary trunk."
NEGATIVE "No aggressive osseous lesion."
NEGATIVE "No incidental finding of note."
"""


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    structures.clear_cache()
    yield
    structures.clear_cache()


def _st():
    st = parse_sheet(SHEET, mode="template").structure
    assert st.usable
    return st


def _jev(picks: dict[str, tuple[str, float]], seen: list):
    """picks: sentence -> (structure name or 'none', confidence)."""
    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        answers = {}
        for k, q in body["questions"].items():
            sentence = q["instructions"].split(": ", 1)[1]
            name, conf = picks[sentence]
            key = next((c for c, text in q["criteria"].items() if text == name), "none")
            answers[k] = {"choice": key, "confidence": conf}
        return httpx.Response(200, json={"answers": answers})
    return httpx.MockTransport(handler)


async def test_a_multi_structure_paragraph_splits_tagged_and_jev_bound_sentences():
    seen: list = []
    t = _jev({"No suspicious parenchymal nodules.": ("LUNGS", 0.95),
              "No pleural or pericardial effusion.": ("EFFUSIONS", 0.9),
              "No aggressive osseous lesion.": ("BONES", 0.97),
              "No incidental finding of note.": ("none", 0.9)}, seen)
    out = await structure_normals(_st(), transport=t)
    assert list(out) == ["Other Findings"]   # a one-structure paragraph is not split
    assert out["Other Findings"] == {
        "Cardiac chambers": ["Normal appearance of the cardiac chambers."],
        "Lungs": ["No suspicious parenchymal nodules."],
        "Effusions": ["No pleural or pericardial effusion."],
        "Great vessels": ["Normal calibre aortic root and pulmonary trunk."],
        "Bones": ["No aggressive osseous lesion."],
    }
    # the unbound sentence stays with the paragraph (absent here), never dropped from the region's normals
    assert "No incidental finding of note." in template_region_normals(_st())["Other Findings"]
    # only untagged sentences are asked, once, in one call
    assert len(seen) == 1 and len(seen[0]["questions"]) == 4


async def test_low_confidence_or_failure_leaves_the_sentence_at_paragraph_level_and_is_not_cached():
    seen: list = []
    t = _jev({"No suspicious parenchymal nodules.": ("LUNGS", 0.4),
              "No pleural or pericardial effusion.": ("EFFUSIONS", 0.9),
              "No aggressive osseous lesion.": ("BONES", 0.9),
              "No incidental finding of note.": ("none", 0.9)}, seen)
    out = await structure_normals(_st(), transport=t)
    assert "Lungs" not in out["Other Findings"]

    def boom(req):
        raise httpx.ConnectError("down")
    structures.clear_cache()
    out = await structure_normals(_st(), transport=httpx.MockTransport(boom))
    # tagged NORMAL lines still split; every untagged negative stays at paragraph level
    assert out["Other Findings"] == {"Cardiac chambers": ["Normal appearance of the cardiac chambers."],
                                     "Great vessels": ["Normal calibre aortic root and pulmonary trunk."]}
    out = await structure_normals(_st(), transport=_jev({
        "No suspicious parenchymal nodules.": ("LUNGS", 0.9), "No pleural or pericardial effusion.": ("EFFUSIONS", 0.9),
        "No aggressive osseous lesion.": ("BONES", 0.9), "No incidental finding of note.": ("none", 0.9)}, []))
    assert "Lungs" in out["Other Findings"]   # a failure was not cached


async def test_the_binding_is_cached_by_sheet_hash():
    seen: list = []
    picks = {"No suspicious parenchymal nodules.": ("LUNGS", 0.9), "No pleural or pericardial effusion.": ("EFFUSIONS", 0.9),
             "No aggressive osseous lesion.": ("BONES", 0.9), "No incidental finding of note.": ("none", 0.9)}
    a = await structure_normals(_st(), transport=_jev(picks, seen))
    b = await structure_normals(_st(), transport=_jev(picks, seen))
    assert a == b and len(seen) == 1


async def test_a_sheet_with_no_multi_structure_paragraph_asks_nothing():
    sheet = SHEET.split("## Paragraph: Other Findings")[0]
    st = parse_sheet(sheet, mode="template").structure
    seen: list = []
    assert await structure_normals(st, transport=_jev({}, seen)) == {} and seen == []
