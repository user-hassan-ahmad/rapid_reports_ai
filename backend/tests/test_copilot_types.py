from rapid_reports_ai.hybrid_stack.copilot import types as T


def test_branch_defaults_and_checked_branches():
    c = T.GuidelineContent(branches=[
        T.Branch(name="A", state="checked", outputs=[T.Output(when="x", classification="I", quote="q")]),
        T.Branch(name="B"),
    ])
    assert c.branches[1].state == "pending"
    assert [b.name for b in c.checked()] == ["A"]
    assert c.branch("B").name == "B" and c.branch("nope") is None


def test_card_id_is_key_and_finding():
    card = T.Card(key="fleischner@2017", name="Fleischner", version="2017", finding_id="u3", branch="Solid")
    assert card.id == "fleischner@2017|u3"
