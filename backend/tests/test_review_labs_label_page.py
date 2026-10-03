import pytest

from rapid_reports_ai.scripts.review_labs import label_page

CARD = {"id": "c2", "title": "Card 2", "meta": "CT · partial",
        "blocks": [{"label": "Dictated line", "text": "A </script> tag"},
                   {"label": "Report", "text": "Full report", "highlight": ["Full"], "collapsed": True}],
        "hidden": [{"label": "Peer read", "text": "action: absent"}]}
FIELDS = [{"key": "verdict", "type": "choice", "options": ["action", "minor", "info", "suppress"], "required": True},
          {"key": "material", "type": "check", "label": "Material loss"},
          {"key": "note", "type": "text"}]


def test_build_page_embeds_data_safely():
    html = label_page.build_page("Gate A labels", "gateA-v1", [CARD], FIELDS)
    assert html.startswith("<!doctype html>")
    assert "<title>Gate A labels</title>" in html
    assert "A </script> tag" not in html
    assert "A <\\/script> tag" in html
    assert '"storage_key": "gateA-v1"' in html


def test_build_page_has_copy_button_and_hidden_gate():
    html = label_page.build_page("t", "k", [CARD], FIELDS)
    assert 'id="copy"' in html and "Copy my verdicts" in html
    assert "function decided(" in html


def test_build_page_rejects_duplicate_ids():
    with pytest.raises(ValueError):
        label_page.build_page("t", "k", [CARD, CARD], FIELDS)
