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
    assert "</script> tag" not in html.split('id="data"', 1)[1].split("</script>", 1)[0]
    assert "A \\u003c/script> tag" in html
    assert '"storage_key": "gateA-v1"' in html


def test_build_page_has_copy_button_and_hidden_gate():
    html = label_page.build_page("t", "k", [CARD], FIELDS)
    assert 'id="copy"' in html and "Copy my verdicts" in html
    assert "function decided(" in html


def test_build_page_rejects_duplicate_ids():
    with pytest.raises(ValueError):
        label_page.build_page("t", "k", [CARD, CARD], FIELDS)


def test_build_page_requires_a_required_field():
    with pytest.raises(ValueError):
        label_page.build_page("t", "k", [CARD], [{"key": "note", "type": "text"}])


def test_inline_script_is_valid_js_and_keeps_last_decided():
    import re
    import shutil
    import subprocess
    import tempfile
    html = label_page.build_page("t", "k", [CARD], FIELDS)
    assert "lastDecided" in html
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(scripts[-1])
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
