# Guideline library sources

One folder per entry, named by the entry id (spec: `docs/superpowers/specs/2026-10-12-guideline-library-design.md`).

- `entry.json`: the entry (inputs, logic, outcomes, reference), facts in our own words, every fact with a locator.
- `manifest.json`: its sources, each with a role (`primary`, `amendment`, `explanatory`).
- `cases.json`: golden cases.
- `sources/<sha256>.pdf` and `.txt`: the publisher files and their `pdftotext -layout` text. Kept on disk for
  authoring and `jev_evidence.py` only; git-ignored and never committed or shipped. Fetch them again from the
  manifest `url` and check the `sha256`.
- `history/<version>.json`: superseded versions, kept so old report stamps resolve.
- `evidence.md` and `review.md`: the gate 5 Jev table and the gate 6 hand read.

After any change: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py`, then
`PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`.
