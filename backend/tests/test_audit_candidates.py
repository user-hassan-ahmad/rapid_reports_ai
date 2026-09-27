from __future__ import annotations

from rapid_reports_ai.audit_candidates import candidates, statements


def test_statements_keep_exact_offsets_and_do_not_split_decimals():
    text = "The right kidney measures 10.5 cm. No hydronephrosis.\n- Small left effusion"
    st = statements(text)
    assert [text[s.start:s.end] for s in st] == ["The right kidney measures 10.5 cm.", "No hydronephrosis.", "Small left effusion"]
    assert st[0].side == "right" and st[0].measures == ("10.5 cm",) and not st[0].negated
    assert st[1].negated


def test_a_negated_and_an_asserted_statement_about_the_same_thing_are_paired():
    text = "No pleural effusion. The heart is normal in size. Small left pleural effusion."
    pairs = [c for c in candidates(text) if c.kind == "pair"]
    assert len(pairs) == 1
    a, b = pairs[0].statements
    assert text[a.start:a.end] == "No pleural effusion." and text[b.start:b.end] == "Small left pleural effusion."


def test_unrelated_statements_are_not_paired():
    text = "No pleural effusion. There is a 9 mm cyst in the liver."
    assert [c for c in candidates(text) if c.kind == "pair"] == []


def test_a_side_is_checked_against_the_history_and_the_other_statements():
    text = "MRI of the right knee. The menisci are intact."
    sides = [c for c in candidates(text, clinical_history="Left knee pain.") if c.kind == "side"]
    assert len(sides) == 1 and text[sides[0].statements[0].start:sides[0].statements[0].end] == "MRI of the right knee."
    assert [c for c in candidates(text, clinical_history="Right knee pain.") if c.kind == "side"] == []


def test_every_measurement_is_a_candidate():
    text = "The aorta measures 55 cm. No haematoma."
    assert [c.kind for c in candidates(text) if c.kind == "measure"] == ["measure"]


def test_candidates_are_capped():
    text = " ".join(f"No effusion {i}. Small effusion {i} measuring {i} mm." for i in range(30))
    cs = candidates(text)
    assert sum(1 for c in cs if c.kind == "pair") <= 12 and len(cs) <= 24


def test_each_negative_statement_is_checked_against_the_whole_scratchpad():
    # different words for the same thing ("haemorrhage" / "haematoma") share no anchor
    text = "No intracranial haemorrhage. There is a thin right subdural haematoma."
    negs = [c for c in candidates(text) if c.kind == "negation"]
    assert [text[c.statements[0].start:c.statements[0].end] for c in negs] == ["No intracranial haemorrhage."]
