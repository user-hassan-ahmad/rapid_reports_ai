import json
from pathlib import Path

CAT = Path(__file__).resolve().parents[2] / "docs" / "guidelines" / "catalogue.json"
FIELDS = {"id", "issuer", "system", "edition", "year", "url", "uk_body", "topic", "finding_types", "modalities",
          "tier_candidate", "licence_notes", "frequency", "frequency_basis"}


def test_catalogue_rows_have_every_field():
    rows = json.loads(CAT.read_text())["systems"]
    assert len(rows) >= 40
    for r in rows:
        assert set(r) == FIELDS, r.get("id")
        assert r["tier_candidate"] in (1, 2) and r["frequency"] in ("high", "medium", "low")
    assert len({r["id"] for r in rows}) == len(rows)
    uk = [r for r in rows if r["uk_body"]]
    assert uk and rows.index(uk[0]) == 0       # UK bodies listed first
