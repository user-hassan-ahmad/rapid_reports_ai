"""The guideline registry (spec §5.1): canonical keys, alias lookup, and a branch-merging upsert. The registry is
small (tens to low hundreds of rows), so alias lookup scans it rather than keeping a second table."""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from ...database.models import GuidelineRegistry
from .types import Branch, Chunk, Entry, GuidelineContent, Publication, Source

_RANK = {"checked": 2, "not_available": 1, "pending": 0}


def _ascii(s: str) -> str:
    # Unicode dash/minus variants (e.g. en dash in "Kellgren–Lawrence") would otherwise be dropped outright by the
    # ascii-ignore encode below, fusing the words instead of hyphenating them.
    s = re.sub(r"[‐-―−]", "-", s)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ascii(name).lower()).strip("-")


def make_key(name: str, version: str) -> str:
    v = re.sub(r"[^0-9a-z.]+", "", _ascii(version or "").lower())
    return f"{slug(name)}@{v}" if v else slug(name)


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _ascii(s or "").lower()).split())


def by_key(db: Session, key: str) -> GuidelineRegistry | None:
    return db.get(GuidelineRegistry, key) if key else None


def by_alias(db: Session, name: str) -> list[GuidelineRegistry]:
    """Every row whose name, alias or key slug is this name (any version): one row is a hit, several go to Jev."""
    n = norm(name)
    if not n:
        return []
    out = []
    for row in db.query(GuidelineRegistry).all():
        names = {norm(row.name), norm(row.key.split("@")[0].replace("-", " ")), *(norm(a) for a in row.aliases or [])}
        if n in names:
            out.append(row)
    return out


def known(db: Session, limit: int = 200) -> list[tuple[str, str, str]]:
    """(key, name, version) for the matcher prompt, so the model reuses registry names."""
    return [(r.key, r.name, r.version) for r in db.query(GuidelineRegistry).order_by(GuidelineRegistry.key).limit(limit)]


def entry(row: GuidelineRegistry) -> Entry:
    return Entry(key=row.key, name=row.name, version=row.version or "", locale=row.locale or "uk",
                 publication=Publication(**(row.publication or {})), status=row.status,
                 content=GuidelineContent(**(row.content or {})), sources=[Source(**s) for s in row.sources or []])


def chunks(row: GuidelineRegistry) -> list[Chunk]:
    return [Chunk(**c) for c in row.chunks or []]


def _merge_branches(old: list[Branch], new: list[Branch], verified: bool) -> list[Branch]:
    by = {b.name: b for b in old}
    for b in new:
        cur = by.get(b.name)
        if cur is None:
            by[b.name] = b
        elif not (verified and cur.state == "checked") and _RANK[b.state] >= _RANK[cur.state]:
            by[b.name] = b
    order = [b.name for b in old] + [b.name for b in new if b.name not in {o.name for o in old}]
    return [by[n] for n in order]


def upsert(db: Session, *, key: str, name: str, version: str, aliases: list[str], publication: Publication | None,
           content: GuidelineContent, sources: list[Source], chunks: list[Chunk]) -> GuidelineRegistry:
    """Insert or merge. Branches merge by name: a better state replaces a worse one (checked > not_available >
    pending); a verified entry's checked branch is never replaced. Sources and chunks accumulate by url/text."""
    row = by_key(db, key)
    if row is None:
        row = GuidelineRegistry(key=key, name=name, version=version or "", aliases=[], status="draft",
                                content=GuidelineContent().model_dump(), sources=[], chunks=[])
        db.add(row)
    old = GuidelineContent(**(row.content or {}))
    merged = GuidelineContent(
        applies_to=old.applies_to or content.applies_to, summary=old.summary or content.summary,
        branches=_merge_branches(old.branches, content.branches, row.status == "verified"),
        supplements=old.supplements + [s for s in content.supplements if s.question not in {o.question for o in old.supplements}])
    row.content = merged.model_dump()
    row.aliases = sorted({*(row.aliases or []), *(norm(a) for a in aliases if norm(a))})
    if publication is not None and not row.publication:
        row.publication = publication.model_dump()
    seen = {s["url"] for s in row.sources or []}
    row.sources = [*(row.sources or []), *(s.model_dump() for s in sources if s.url not in seen)]
    seen_c = {(c["url"], c["text"]) for c in row.chunks or []}
    row.chunks = [*(row.chunks or []), *(c.model_dump() for c in chunks if (c.url, c.text) not in seen_c)]
    db.commit()
    return row
