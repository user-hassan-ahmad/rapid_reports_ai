"""The guideline registry (spec §5.1): canonical keys, alias lookup, and a branch-merging upsert. The registry is
small (tens to low hundreds of rows), so alias lookup scans it rather than keeping a second table."""
from __future__ import annotations

import re
import unicodedata

import sqlalchemy.exc
from sqlalchemy.orm import Session, defer

from ...database.models import GuidelineRegistry
from .types import Branch, Chunk, Entry, GuidelineContent, Publication, Source

_RANK = {"checked": 2, "not_available": 1, "pending": 0}

# A trailing version-ish token ("Fleischner 2017", "Bosniak v2019", "Kellgren Lawrence 2nd edition") so an alias
# lookup that includes the year/edition still matches a registry name stored without one.
_VERSION_TOKEN = re.compile(r"\s+v?\d{4}$|\s+v?\d+(?:\.\d+)?(?:st|nd|rd|th)?(?: edition)?$")


def _ascii(s: str) -> str:
    # Unicode dash/minus variants (e.g. en dash in "Kellgren–Lawrence") would otherwise be dropped outright by the
    # ascii-ignore encode below, fusing the words instead of hyphenating them.
    s = re.sub(r"[‐-―−]", "-", s)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _ascii(name).lower()).strip("-")
    return s[:100].rstrip("-")


def make_key(name: str, version: str) -> str:
    v = re.sub(r"[^0-9a-z.]+", "", _ascii(version or "").lower())[:24]
    return f"{slug(name)}@{v}" if v else slug(name)


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _ascii(s or "").lower()).split())


def _strip_version(n: str) -> str:
    return _VERSION_TOKEN.sub("", n).strip()


def by_key(db: Session, key: str) -> GuidelineRegistry | None:
    return db.get(GuidelineRegistry, key) if key else None


def _fresh(db: Session, key: str) -> GuidelineRegistry | None:
    """Re-read the row locked and bypassing the identity map, just before merging. A session that loaded this row
    long ago — before an await — must merge onto what is actually committed now, not what it saw then, or it
    overwrites a sibling session's branches (lost-update guard, review)."""
    if not key:
        return None
    return db.get(GuidelineRegistry, key, populate_existing=True, with_for_update=True)


def alias_hit(row: GuidelineRegistry, n: str, n_stripped: str) -> bool:
    """Whether a normalised name (`n`, or `n_stripped`: the same with a trailing version token removed) is this row's
    name, an alias, or its key slug."""
    names = {norm(row.name), norm(row.key.split("@")[0].replace("-", " ")), *(norm(a) for a in row.aliases or [])}
    return n in names or bool(n_stripped and n_stripped in names)


def by_alias(db: Session, name: str) -> list[GuidelineRegistry]:
    """Every row whose name, alias or key slug is this name (any version): one row is a hit, several go to Jev.
    Matches with a trailing version/edition token stripped too, so "Fleischner 2017" still finds "Fleischner".
    Chunks are deferred: by_alias and the entry() built from its rows never read them."""
    n = norm(name)
    if not n:
        return []
    n_stripped = _strip_version(n)
    return [row for row in db.query(GuidelineRegistry).options(defer(GuidelineRegistry.chunks)).all()
            if alias_hit(row, n, n_stripped)]


def known(db: Session, limit: int = 200) -> list[tuple[str, str, str]]:
    """(key, name, version) for the matcher prompt, so the model reuses registry names. Queries only those three
    columns — content/sources/chunks never need to load for this."""
    rows = (db.query(GuidelineRegistry.key, GuidelineRegistry.name, GuidelineRegistry.version)
              .order_by(GuidelineRegistry.key).limit(limit).all())
    return [(k, nm, v) for k, nm, v in rows]


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
            # >= , not >: on a draft, the latest fetch of the same state wins.
            by[b.name] = b
    order = [b.name for b in old] + [b.name for b in new if b.name not in {o.name for o in old}]
    return [by[n] for n in order]


def _merge_onto(row: GuidelineRegistry, *, name: str, version: str, aliases: list[str],
                 publication: Publication | None, content: GuidelineContent, sources: list[Source],
                 chunks: list[Chunk]) -> None:
    """Merge the incoming guideline onto `row` in place. Sources (by url), chunks (by url, text) and supplements
    (by question) dedupe against what's already stored *and* against earlier items in this same call."""
    old = GuidelineContent(**(row.content or {}))

    seen_q = {o.question for o in old.supplements}
    new_supplements = []
    for sup in content.supplements:
        if sup.question in seen_q:
            continue
        seen_q.add(sup.question)
        new_supplements.append(sup)

    merged = GuidelineContent(
        applies_to=old.applies_to or content.applies_to, summary=old.summary or content.summary,
        branches=_merge_branches(old.branches, content.branches, row.status == "verified"),
        supplements=old.supplements + new_supplements)
    row.content = merged.model_dump()
    row.aliases = sorted({*(row.aliases or []), *(norm(a) for a in aliases if norm(a))})
    if publication is not None and not row.publication:
        row.publication = publication.model_dump()

    seen = {s["url"] for s in row.sources or []}
    new_sources = []
    for s in sources:
        if s.url in seen:
            continue
        seen.add(s.url)
        new_sources.append(s.model_dump())
    row.sources = [*(row.sources or []), *new_sources]

    seen_c = {(c["url"], c["text"]) for c in row.chunks or []}
    new_chunks = []
    for c in chunks:
        k = (c.url, c.text)
        if k in seen_c:
            continue
        seen_c.add(k)
        new_chunks.append(c.model_dump())
    row.chunks = [*(row.chunks or []), *new_chunks]


def upsert(db: Session, *, key: str, name: str, version: str, aliases: list[str], publication: Publication | None,
           content: GuidelineContent, sources: list[Source], chunks: list[Chunk]) -> GuidelineRegistry:
    """Insert or merge. Branches merge by name: a better state replaces a worse one (checked > not_available >
    pending); a verified entry's checked branch is never replaced. Sources and chunks accumulate by url/text.

    Re-reads the row locked right before merging (`_fresh`) rather than trusting an earlier lookup, so a session
    that loaded the row before a long await still merges onto the latest commit instead of clobbering it. A new
    key racing a sibling session's insert loses the unique-key race on commit; that's caught once and retried
    through the merge path, since by then the sibling's row exists to merge onto."""
    if not key or key.startswith("@"):
        raise ValueError(f"invalid guideline key: {key!r}")

    row = _fresh(db, key)
    if row is not None:
        _merge_onto(row, name=name, version=version, aliases=aliases, publication=publication, content=content,
                    sources=sources, chunks=chunks)
        db.commit()
        return row

    row = GuidelineRegistry(key=key, name=name, version=version or "", aliases=[], status="draft",
                            content=GuidelineContent().model_dump(), sources=[], chunks=[])
    db.add(row)
    _merge_onto(row, name=name, version=version, aliases=aliases, publication=publication, content=content,
                sources=sources, chunks=chunks)
    try:
        db.commit()
    except sqlalchemy.exc.IntegrityError:
        db.rollback()
        row = _fresh(db, key)
        if row is None:
            raise
        _merge_onto(row, name=name, version=version, aliases=aliases, publication=publication, content=content,
                    sources=sources, chunks=chunks)
        db.commit()
    return row
