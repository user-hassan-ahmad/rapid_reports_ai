from rapid_reports_ai.scripts.review_labs.negatives_bundle import build_bundle

CASE = {"id8": "syn1", "scan": "CT abdomen", "history": "pain", "dictation": "Gallstones."}
REPORT = ("FINDINGS:\nGallstones are present. No biliary dilatation. The liver is normal. "
          "No free fluid, collection, or pneumoperitoneum. The bile duct measures 5 mm.\n\nIMPRESSION:\nCholelithiasis.")
CANDS = [{"clause": "No biliary dilatation.", "number_code": False},
         {"clause": "The liver is normal.", "number_code": False},
         {"clause": "No collection", "number_code": False},
         {"clause": "The bile duct measures 5 mm.", "number_code": True}]
LABELS = {"1": {"cls": "implicated", "pointer": "Gallstones"}, "2": {"cls": "default"},
          "3": {"cls": "contradicted", "pointer": "collection dictated"}, "4": {"cls": "default"}}


def test_bundle_document_excludes_removed_and_keeps_marks_aligned():
    b = build_bundle(CASE, REPORT, [dict(c) for c in CANDS], LABELS,
                     [{"id": "fn0", "section": "FINDINGS", "sentence": "No gallbladder wall thickening."}])
    doc = b["report"]
    assert "collection" not in doc and "5 mm" not in doc
    assert "No free fluid or pneumoperitoneum." in doc
    assert {r["reason"] for r in b["removed"]} == {"contradicted", "number"}
    for m in b["marked"]:
        assert doc[m["start"]:m["end"]] == m["text"]
    assert [m["cls"] for m in b["marked"]] == ["implicated", "default"]
    for r in b["removed"]:
        assert 0 <= r["anchor"] <= len(doc)
    assert b["options"][0]["anchor"] == doc.index("\n\nIMPRESSION")


def test_restoring_removed_text_at_anchor_reproduces_original_wording():
    b = build_bundle(CASE, REPORT, [dict(c) for c in CANDS], LABELS)
    num = next(r for r in b["removed"] if r["reason"] == "number")
    restored = b["report"][:num["anchor"]] + num["text"] + b["report"][num["anchor"]:]
    assert "The bile duct measures 5 mm." in restored


def test_contradicted_item_code_cannot_remove_falls_back_to_amber_mark():
    rep = "FINDINGS:\nGallstones. No free fluid, collection or pneumoperitoneum.\n\nIMPRESSION:\nX."
    b = build_bundle(CASE, rep, [{"clause": "No collection", "number_code": False}],
                     {"1": {"cls": "contradicted", "pointer": "collection"}})
    assert b["report"] == rep and b["removed"] == []
    assert [(m["cls"], m["text"]) for m in b["marked"]] == [("implicated", "collection")]


def test_number_in_a_dictated_sentence_is_amber_not_removed():
    rep = "FINDINGS:\nThe uterus is normal, with a junctional zone under 12 mm.\n\nIMPRESSION:\nNormal."
    b = build_bundle(CASE, rep, [{"clause": "The uterus is normal, with a junctional zone under 12 mm.", "number_code": True}],
                     {"1": {"cls": "dictated", "pointer": "normal uterus"}})
    assert b["report"] == rep and b["removed"] == []
    assert [m["cls"] for m in b["marked"]] == ["implicated"]


def test_amber_items_carry_a_check_reason_and_evidence():
    rep = ("FINDINGS:\nGallstones. No free fluid, collection or pneumoperitoneum. "
           "The uterus is normal, with a junctional zone under 12 mm. No duct dilatation.\n\nIMPRESSION:\nX.")
    cands = [{"clause": "No collection", "number_code": False},
             {"clause": "The uterus is normal, with a junctional zone under 12 mm.", "number_code": True},
             {"clause": "No duct dilatation.", "number_code": False}]
    labels = {"1": {"cls": "contradicted", "pointer": "collection in the gallbladder fossa"},
              "2": {"cls": "dictated", "pointer": "normal uterus"},
              "3": {"cls": "implicated", "pointer": "Gallstones"}}
    b = build_bundle({**CASE, "dictation": "Gallstones. Normal uterus."}, rep, cands, labels)
    got = {m["text"]: (m["reason"], m["pointer"]) for m in b["marked"]}
    assert got["collection"] == ("conflict", "collection in the gallbladder fossa")
    assert got["The uterus is normal, with a junctional zone under 12 mm"] == ("number", "12 mm")
    assert got["No duct dilatation"] == ("uncertain", "Gallstones")
