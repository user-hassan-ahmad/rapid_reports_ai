"""Pure helpers of the hybrid certainty-rule validation lab. Synthetic text only, no model calls."""
from rapid_reports_ai.scripts.review_labs import hybrid_lab as HL


def test_flag_is_the_hybrid_rule():
    assert HL.flag("fact", "probable", None) is True
    assert HL.flag("probable", "probable", 0.99) is False
    assert HL.flag("fact", "fact", 0.6) is True and HL.flag("fact", "fact", 0.4) is False
    assert HL.flag("fact", "not_stated", 0.9) is None and HL.flag("fact", None, 0.9) is None


def test_real_hedges_hit_their_intended_code_tier():
    for word, (tier, _, _) in HL.REAL_HEDGES.items():
        assert HL.report_tier(HL.hedge("Mild wall thickening", "chronic inflammation", word)) == tier, word
        assert HL.report_tier(HL.hedge("", "a fracture", word)) == tier, word


def test_real_hedge_items_label_by_construction():
    src = [{"sid": "q", "case_key": "b:x", "obs": "Calcified foci", "finding": "scarring", "dict_tier": "probable"},
           {"sid": "p", "case_key": "b:y", "obs": "", "finding": "a fracture", "dict_tier": "possible"}]
    items = HL.real_hedge_items(src)
    rels = sorted((i["id"], i["relation"]) for i in items)
    assert ("d-q-suspicious_for", "same") in rels and ("d-q-raises_the_possibility_of", "downgrade") in rels
    assert ("d-p-suspicious_for", "upgrade") in rels and ("d-p-raises_the_possibility_of", "same") in rels
