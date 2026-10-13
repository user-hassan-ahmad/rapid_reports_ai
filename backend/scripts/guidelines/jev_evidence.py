"""Gate 5 (library spec §8): Jev checks each located fact of an entry against its source text (the locator's page
and its neighbours, from the manifest's text_file). Prints a markdown table; save it as <entry>/evidence.md.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/<entry-id>"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import jev as J  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.describe import facts  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, Manifest  # noqa: E402


def source_text(d: Path, m: Manifest, source: str, page: int | None) -> str:
    src = next(s for s in m.sources if s.id == source)
    pages = (d / src.text_file).read_text().split("\f")
    if page is None:
        return "\n".join(pages)
    return "\n".join(pages[max(page - 2, 0):page + 1])      # 1-based page, with one page either side


async def main(d: Path) -> int:
    e = Entry.model_validate_json((d / "entry.json").read_text())
    m = Manifest.model_validate_json((d / "manifest.json").read_text())
    groups: dict[tuple, list] = {}
    for fid, claim, loc in facts(e):
        groups.setdefault((loc.source, loc.page), []).append((fid, claim))
    rows = []
    for (source, page), items in groups.items():
        scores = await J.evidence(source_text(d, m, source, page), [("", f"{e.display}: {c}") for _, c in items])
        rows += [(fid, c, s, source, page) for (fid, c), s in zip(items, scores)]
    low = 0
    print(f"# Gate 5: Jev evidence for {e.key}\n\n| field | claim | source | Jev | |\n|---|---|---|---|---|")
    for fid, c, s, source, page in rows:
        flag = s < J.EVIDENCE_MIN
        low += flag
        print(f"| {fid} | {c} | {source} p{page} | {s:.2f} | {'**check**' if flag else ''} |")
    print(f"\n{len(rows)} facts; {low} below {J.EVIDENCE_MIN}: read each against the source in review.md.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]).resolve())))
