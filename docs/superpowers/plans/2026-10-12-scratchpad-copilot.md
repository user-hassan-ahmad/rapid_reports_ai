# Scratchpad Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a side panel next to the dictation scratchpad. It holds guideline cards matched to the dictated findings,
built from a lazily filled and source-checked guideline registry. Explicit Apply adds a classification line to the
finding and a recommendation to a ticked checklist under the conclusion. One ask input files questions into card
threads.

**Spec:** `docs/superpowers/specs/2026-10-12-scratchpad-copilot-design.md`. Read it first. Its §2 decision list is
binding.

**Architecture:**
- **Backend:** a new package `hybrid_stack/copilot/` behind `/api/canvas/stack/guidelines/*`.
  - matcher: gpt-oss, which also returns the skeleton and the case's branch;
  - targeted fetch: Tavily search and extract, Jev coverage and evidence checks, gpt-oss structure, upserted into
    `guideline_registry`;
  - preview: Qwen plus a numeric guard;
  - ask: Qwen, with a Jev gate before any new search;
  - recommendations: Qwen.
- **Frontend:**
  - a pure state module (`copilot.ts`);
  - `CopilotPanel.svelte`, mounted in the scratchpad's margin column;
  - enrichment lines and a Recommendations checklist in `HybridStackView.svelte`;
  - the gate record and the findings block carry enrichments and ticked recommendations.
- **Generate:** the quick `stack_fallback` brief gains a rule that turns the findings block's recommendations line
  into a RECOMMENDATIONS section.

**Tech stack:**
- Backend: FastAPI, SQLAlchemy and alembic; pydantic-ai through `_run_agent_with_model`; Jev via `jev_post`; Tavily via
  `AsyncTavilyClient`; pytest (`asyncio_mode = auto`, `httpx.MockTransport`).
- Frontend: SvelteKit with Svelte 5. The scratchpad is in legacy mode (`export let`, `$:`); new components use runes.
  Tests use vitest and vitest-browser-svelte.

**Working directory:** worktree `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot`, branch
`feat/scratchpad-copilot`, cut from `feat/hybrid-stack`.
- Backend commands run from `backend/`:
  `cd backend && PYTHONPATH=src poetry run pytest …`, or the worktree venv `PYTHONPATH=src .venv/bin/pytest …` if
  poetry is absent. The editable install points at the main checkout, so **always set `PYTHONPATH=src`**.
- Frontend commands run from `frontend/`: `npx vitest run <file>`, plus `npm run check` for types.

**Standing rules for every task:**
- **Prompts are case-agnostic.** Use structural form or multi-domain breadth, never a single-domain clinical example.
  This is a memory rule.
- **Fail open everywhere.** No Copilot failure may block dictation, Confirm or Generate.
- **No dictated text in any search query** (spec §2.18).
- Match the surrounding code: terse docstrings that say *why*, the house comment density, British English in
  user-facing strings.
- Commit after each task with a conventional message ending in the attribution line:
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

**Provisional thresholds.** Task 13's lab sets the final values. Until then the code uses these, defined once in
`copilot/jev.py`:
- `COVER_MIN = 0.7`
- `EVIDENCE_MIN = 0.8`
- `ANSWERS_MIN = 0.7`

---

## File map

**Backend** (`backend/src/rapid_reports_ai/`)

| File | Responsibility |
|---|---|
| `hybrid_stack/copilot/__init__.py` | package marker |
| `hybrid_stack/copilot/types.py` | pydantic types shared by every copilot module and route |
| `hybrid_stack/copilot/registry.py` | keys, aliases, lookup, branch-merging upsert, row → `Entry` |
| `hybrid_stack/copilot/jev.py` | coverage, evidence, "answers the question" (Jev) and thresholds |
| `hybrid_stack/copilot/search.py` | identity-only query builders, tier ranking, the Tavily search/extract wrapper |
| `hybrid_stack/copilot/fetch.py` | gpt-oss structure call; `resolve_guideline` (first pass, background fill, locks) |
| `hybrid_stack/copilot/matcher.py` | gpt-oss match (skeleton + branch), per-unit cache, normalisation, caps |
| `hybrid_stack/copilot/preview.py` | Qwen preview, validation, numeric guard |
| `hybrid_stack/copilot/ask.py` | ask flow: route, gate, targeted gap search, supplements |
| `hybrid_stack/copilot/recs.py` | general recommendation suggestions |
| `hybrid_stack/copilot/routes.py` | `/api/canvas/stack/guidelines/*`, kill switch, reviewer registry routes |
| `database/models.py` | `GuidelineRegistry` model; `DictationStackLog.copilot` column |
| `migrations/versions/20261012150000_guideline_registry.py` | the table and the column |
| `hybrid_stack/routes.py` | `LogRequest.copilot` |
| `main.py` | include the router; `stack_copilot` status flag |
| `quick_report_brief.py` | `stack_fallback` recommendations rule |

**Backend tests** (`backend/tests/`): `test_copilot_registry.py`, `test_copilot_jev.py`, `test_copilot_search.py`,
`test_copilot_fetch.py`, `test_copilot_matcher.py`, `test_copilot_preview.py`, `test_copilot_ask.py`,
`test_copilot_recs.py`, `test_copilot_routes.py`, plus additions to `test_hybrid_stack_generate.py` or the existing
`stack_fallback` test file (find it with `grep -ln stack_fallback tests`). Also `conftest.py`, where the table is
registered.

**Labs** (`backend/scripts/copilot_eval/`): `seed_fetch_lab.py`, `match_preview_ask_lab.py`, `fixtures/*.json`. Outputs
go to the session scratchpad, never the repo.

**Frontend** (`frontend/src/`)

| File | Responsibility |
|---|---|
| `lib/hybrid-stack/types.ts` | copilot types; `GateRecord.enrichments` and `.recommendations` |
| `lib/hybrid-stack/api.ts` | `postMatch`, `postOpen`, `postPreview`, `postAsk`, `postRecommendations` |
| `lib/hybrid-stack/copilot.ts` | pure state: cards per finding, thread routing, enrichments, recommendation merge, findings lines |
| `lib/hybrid-stack/regionState.ts` | `buildFindingsBlock` adds enrichment lines and the recommendations line |
| `lib/hybrid-stack/CopilotPanel.svelte` | the side panel |
| `lib/hybrid-stack/HybridStackView.svelte` | enrichment lines under findings; Recommendations checklist under the conclusion |
| `lib/components/DictationScratchpad.svelte` | orchestration: match, open, preview, apply, ask, recommendations, gate, log |
| `routes/components/IntelliDictateTab.svelte`, `routes/components/TemplateForm.svelte` | pass the `stackCopilot` flag |
| `routes/stack-guidelines/+page.svelte` | registry review page |

Tests: `copilot.test.ts`, `api.test.ts` (additions), `regionState.test.ts` (additions),
`CopilotPanel.svelte.test.ts`, `HybridStackView.svelte.test.ts` (additions).

---

# Phase A: backend core

### Task 1: Copilot types

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/__init__.py`
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py`
- Test: `backend/tests/test_copilot_types.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_types.py
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
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_types.py -v`
Expected: FAIL with `ModuleNotFoundError: ... copilot`.

- [ ] **Step 3: Write the types**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/__init__.py
"""Scratchpad Copilot (spec 2026-10-12-scratchpad-copilot): guideline cards, the registry and its targeted fetch."""
```

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py
"""Types shared by the Copilot's modules and routes (spec §5). The registry caches a guideline; nothing here holds
how it applied to a case except Preview, which is never stored."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BranchState = Literal["checked", "not_available", "pending"]


class Input(BaseModel):
    id: str
    question: str
    options: list[str] = Field(default_factory=list)
    settled_by: str = ""


class Output(BaseModel):
    when: str = ""
    classification: str = ""
    recommendation: str = ""
    quote: str = ""               # verbatim evidence from the fetched chunks


class Branch(BaseModel):
    name: str
    state: BranchState = "pending"
    inputs: list[Input] = Field(default_factory=list)
    rule: str = ""
    outputs: list[Output] = Field(default_factory=list)


class Supplement(BaseModel):
    question: str
    answer: str
    quote: str = ""
    url: str = ""


class GuidelineContent(BaseModel):
    applies_to: str = ""
    summary: str = ""
    branches: list[Branch] = Field(default_factory=list)
    supplements: list[Supplement] = Field(default_factory=list)

    def branch(self, name: str) -> Branch | None:
        return next((b for b in self.branches if b.name == name), None)

    def checked(self) -> list[Branch]:
        return [b for b in self.branches if b.state == "checked"]


class Publication(BaseModel):
    title: str = ""
    body: str = ""
    year: str = ""


class Source(BaseModel):
    url: str
    title: str = ""
    tier: int = 3
    fetched_at: str = ""


class Chunk(BaseModel):
    url: str
    text: str
    branch: str = ""              # the branch whose query found it ("" for the publication query)


class Entry(BaseModel):
    """The API view of one registry row."""
    key: str
    name: str
    version: str = ""
    locale: str = "uk"
    publication: Publication = Field(default_factory=Publication)
    status: Literal["draft", "verified"] = "draft"
    content: GuidelineContent = Field(default_factory=GuidelineContent)
    sources: list[Source] = Field(default_factory=list)


class Card(BaseModel):
    key: str
    name: str
    version: str = ""
    finding_id: str               # the abnormal item it applies to (frontend id: "u<unit>" or "u<unit>.<part>")
    why: str = ""
    branch: str = ""              # the skeleton branch this finding falls into
    skeleton: list[str] = Field(default_factory=list)
    publication: Publication = Field(default_factory=Publication)
    known: bool = False           # already in the registry
    status: Literal["draft", "verified", "new"] = "new"

    @property
    def id(self) -> str:
        return f"{self.key}|{self.finding_id}"


class Settled(BaseModel):
    input: str
    value: str
    quote: str = ""


class Proposal(BaseModel):
    classification: str
    line: str
    recommendation: str = ""


class Preview(BaseModel):
    settled: list[Settled] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    proposal: Proposal | None = None
```

- [ ] **Step 4: Run the test and check it passes**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_types.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot backend/tests/test_copilot_types.py
git commit -m "feat(copilot): shared types for cards, registry entries and previews"
```

---

### Task 2: Registry table, migration and registry module

**Files:**
- Modify: `backend/src/rapid_reports_ai/database/models.py`. Add `GuidelineRegistry` after `StackSlimSheet`, and add
  `copilot` to `DictationStackLog`.
- Create: `backend/migrations/versions/20261012150000_guideline_registry.py`
- Modify: `backend/tests/conftest.py` (import and add `GuidelineRegistry.__table__` to `_TEST_TABLES`)
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/registry.py`
- Test: `backend/tests/test_copilot_registry.py`

- [ ] **Step 1: Check the migration head**

Run: `cd backend && grep -rl "down_revision.*20261012090000" migrations/versions`
Expected: no output, so `20261012090000` is the head. If a file prints, use its revision as `down_revision` below.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_copilot_registry.py
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, GuidelineContent, Output, Publication, Source


def test_make_key_and_slug():
    assert R.make_key("Fleischner Society", "2017") == "fleischner-society@2017"
    assert R.make_key("Kellgren–Lawrence", "") == "kellgren-lawrence"
    assert R.norm("  Bosniak  (2019) ") == "bosniak 2019"


def _content(state="checked"):
    return GuidelineContent(summary="s", branches=[Branch(name="Solid", state=state,
                            outputs=[Output(when="<6 mm", classification="No follow-up", quote="q")])])


def test_upsert_merges_branches_and_lookup(db_session):
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=["fleischner society"],
             publication=Publication(title="Guidelines for…", body="Fleischner Society", year="2017"),
             content=_content(), sources=[Source(url="https://a", tier=1)], chunks=[])
    sub = GuidelineContent(branches=[Branch(name="Subsolid", state="checked", outputs=[Output(classification="x", quote="q")])])
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=[], publication=None,
             content=sub, sources=[Source(url="https://b", tier=2)], chunks=[])
    e = R.entry(R.by_key(db_session, "fleischner@2017"))
    assert [b.name for b in e.content.branches] == ["Solid", "Subsolid"]
    assert {s.url for s in e.sources} == {"https://a", "https://b"}
    assert e.content.summary == "s"                    # a later upsert with no summary keeps the first
    assert [r.key for r in R.by_alias(db_session, "Fleischner Society")] == ["fleischner@2017"]
    assert [r.key for r in R.by_alias(db_session, "fleischner")] == ["fleischner@2017"]


def test_upsert_never_overwrites_verified_branch(db_session):
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    R.by_key(db_session, "k@1").status = "verified"
    db_session.commit()
    worse = GuidelineContent(branches=[Branch(name="Solid", state="not_available")])
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=worse,
             sources=[], chunks=[])
    assert R.entry(R.by_key(db_session, "k@1")).content.branch("Solid").state == "checked"


def test_pending_never_replaces_checked(db_session):
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Solid", state="pending")]), sources=[], chunks=[])
    assert R.entry(R.by_key(db_session, "k@1")).content.branch("Solid").state == "checked"


def test_known_list(db_session):
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    assert R.known(db_session) == [("k@1", "K", "1")]
```

- [ ] **Step 3: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_registry.py -v`
Expected: FAIL (an import error on `registry`).

- [ ] **Step 4: Add the model, the migration and the conftest registration**

In `database/models.py`, after the `StackSlimSheet` class:

```python
class GuidelineRegistry(Base):
    """Scratchpad Copilot registry (spec 2026-10-12-scratchpad-copilot §5.1): one row per guideline version, shared by
    every user. Filled lazily by the targeted fetch (status draft) and verified by a reviewer. Holds the guideline,
    never how it applied to a case."""
    __tablename__ = "guideline_registry"
    key = Column(String(128), primary_key=True)          # slug@version
    name = Column(Text, nullable=False)
    version = Column(String(32), nullable=False, default="")
    locale = Column(String(8), nullable=False, default="uk")
    publication = Column(JSONBType(), nullable=True)     # {title, body, year}
    aliases = Column(JSONBType(), nullable=False, default=list)
    status = Column(String(16), nullable=False, default="draft")
    content = Column(JSONBType(), nullable=False)        # GuidelineContent
    sources = Column(JSONBType(), nullable=False, default=list)
    chunks = Column(JSONBType(), nullable=False, default=list)
    verified_by = Column(Text, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
```

In `DictationStackLog`, after `report_id`:

```python
    copilot = Column(JSONBType(), nullable=True)         # Copilot: cards matched/opened/applied, threads, recommendations
```

In `tests/conftest.py`, add `GuidelineRegistry` to the models import list and `GuidelineRegistry.__table__,` to
`_TEST_TABLES`.

```python
# backend/migrations/versions/20261012150000_guideline_registry.py
"""guideline_registry table and dictation_stack_logs.copilot (scratchpad copilot §5.1, §5.7)

Revision ID: 20261012150000
Revises: 20261012090000
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261012150000"
down_revision: Union[str, Sequence[str], None] = "20261012090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = postgresql.JSONB if op.get_bind().dialect.name == "postgresql" else sa.JSON
    op.create_table(
        "guideline_registry",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="uk"),
        sa.Column("publication", json_type(), nullable=True),
        sa.Column("aliases", json_type(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("content", json_type(), nullable=False),
        sa.Column("sources", json_type(), nullable=False),
        sa.Column("chunks", json_type(), nullable=False),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column("dictation_stack_logs", sa.Column("copilot", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("dictation_stack_logs", "copilot")
    op.drop_table("guideline_registry")
```

- [ ] **Step 5: Write the registry module**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/registry.py
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
```

- [ ] **Step 6: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_registry.py tests/test_hybrid_stack_models.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/database/models.py backend/migrations/versions/20261012150000_guideline_registry.py \
  backend/tests/conftest.py backend/src/rapid_reports_ai/hybrid_stack/copilot/registry.py backend/tests/test_copilot_registry.py
git commit -m "feat(copilot): guideline_registry table, migration and branch-merging registry"
```

---

### Task 3: Jev gates (coverage, evidence, answers)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/jev.py`
- Test: `backend/tests/test_copilot_jev.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_jev.py
import json

import httpx

from rapid_reports_ai.hybrid_stack.copilot import jev as J


def _jev(scores: dict[str, float], seen: dict):
    def handler(req):
        body = json.loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={"answers": {k: {"noul": scores.get(k, 0.0)} for k in body["questions"]}})
    return httpx.MockTransport(handler)


async def test_coverage_one_call_one_question_per_branch(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    out = await J.coverage("chunk text", ["Solid", "Subsolid"], transport=_jev({"b_0": 0.9, "b_1": 0.2}, seen))
    assert out == {"Solid": 0.9, "Subsolid": 0.2}
    assert "Subsolid" in seen["questions"]["b_1"]["instructions"] and seen["state"].startswith("SOURCE:")


def test_exact_quote_normalises_whitespace_and_case():
    assert J.quote_in("Nodules  <6 mm:\nNo routine follow-up", "nodules <6 mm: no ROUTINE follow-up")
    assert not J.quote_in("Nodules <6 mm", "Nodules <8 mm")
    assert not J.quote_in("x", "")


async def test_evidence_skips_jev_for_exact_quotes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    claims = [("No routine follow-up", "exact"), ("CT at 3 months", "reworded claim")]
    scores = await J.evidence("SOURCE … No routine follow-up …", claims, transport=_jev({"c_1": 0.85}, seen))
    assert scores == [1.0, 0.85]
    assert list(seen["questions"]) == ["c_1"]


async def test_evidence_without_jev_need_makes_no_call():
    assert await J.evidence("abc", [("abc", "abc")]) == [1.0]


async def test_answers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    assert await J.answers("material", "Does X change it?", transport=_jev({"q": 0.75}, seen)) == 0.75


def test_state_is_capped():
    assert len(J._state("x" * 50000)) <= J.STATE_MAX + 20
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_jev.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the Jev gates**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/jev.py
"""Jev gates of the targeted fetch (spec §2.20, §5.3, §5.5): judgements about meaning over source text. Code does
only the exact-quote first pass. Thresholds are provisional until the seed lab (plan Task 13) sets them where false
yes answers reach zero."""
from __future__ import annotations

import os
import re
from typing import Any

from ...jev_client import JEV_MODEL, jev_post

TIMEOUT_S = 6.0
STATE_MAX = 12000          # chars of source text per Jev call

COVER_MIN = 0.7            # provisional: SOURCE states the criteria or management for a branch
EVIDENCE_MIN = 0.8         # provisional: SOURCE states a claim whose quote is not an exact match
ANSWERS_MIN = 0.7          # provisional: the stored material answers a radiologist's question


def _state(source: str) -> str:
    return "SOURCE:\n" + source[:STATE_MAX]


def _flat(s: str) -> str:
    return " ".join(re.sub(r"[^\w<>≤≥=.%/+-]+", " ", s.lower()).split())


def quote_in(source: str, quote: str) -> bool:
    """The exact-match first pass: the quote appears in the source once whitespace, case and punctuation runs are
    flattened (tables lose their layout in extraction; meaning-level matches go to Jev)."""
    q = _flat(quote)
    return bool(q) and q in _flat(source)


async def _ask(state: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return {k: float((ans.get(k) or {}).get("noul") or 0.0) for k in questions}


async def coverage(source: str, branches: list[str], transport=None) -> dict[str, float]:
    """P(the SOURCE sets out the criteria or management for each branch), one call."""
    if not branches:
        return {}
    qs = {f"b_{i}": {"type": "noul", "instructions": (
        "The SOURCE states the classification criteria or the management recommendations for this case of the "
        f"guideline (not only mentions it): {b}")} for i, b in enumerate(branches)}
    got = await _ask(_state(source), qs, transport)
    return {b: got[f"b_{i}"] for i, b in enumerate(branches)}


async def evidence(source: str, claims: list[tuple[str, str]], transport=None) -> list[float]:
    """Per (quote, claim): 1.0 when the quote is an exact match; otherwise P(the SOURCE states the claim)."""
    out: list[float] = [1.0 if quote_in(source, q) else -1.0 for q, _ in claims]
    need = {f"c_{i}": {"type": "noul", "instructions": f"The SOURCE states this, with the same values: {c}"}
            for i, (_, c) in enumerate(claims) if out[i] < 0}
    if need:
        got = await _ask(_state(source), need, transport)
        for k, v in got.items():
            out[int(k[2:])] = v
    return out


async def answers(material: str, question: str, transport=None) -> float:
    """P(the stored guideline material answers the radiologist's question)."""
    got = await _ask(_state(material), {"q": {"type": "noul", "instructions": (
        f"The SOURCE contains the answer to this question: {question}")}}, transport)
    return got["q"]
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_jev.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/jev.py backend/tests/test_copilot_jev.py
git commit -m "feat(copilot): Jev coverage, evidence and answers gates with exact-quote first pass"
```

---

### Task 4: Search (identity-only queries, tier ranking, Tavily)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/search.py`
- Test: `backend/tests/test_copilot_search.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_search.py
from rapid_reports_ai.hybrid_stack.copilot import search as S
from rapid_reports_ai.hybrid_stack.copilot.types import Publication


def test_queries_use_identity_only():
    pub = Publication(title="Guidelines for Management of Incidental Pulmonary Nodules", body="Fleischner Society", year="2017")
    q = S.first_pass_queries("Fleischner", "2017", pub, "Subsolid · part-solid · ≥ 6 mm")
    assert q == ['"Guidelines for Management of Incidental Pulmonary Nodules" 2017',
                 "Fleischner 2017 Subsolid part-solid ≥ 6 mm criteria recommendations"]
    assert S.branch_query("Fleischner", "2017", "Solid · single") == "Fleischner 2017 Solid single recommendations"


def test_first_pass_without_publication_falls_back_to_name():
    q = S.first_pass_queries("Bosniak", "2019", Publication(), "")
    assert q == ["Bosniak 2019 classification", "Bosniak 2019 criteria recommendations"]


def test_tier_ranking():
    assert S.tier("https://pubs.rsna.org/doi/10.1148/radiol.2017161659") == 1
    assert S.tier("https://www.rcr.ac.uk/x") == 1
    assert S.tier("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/") == 2
    assert S.tier("https://radiopaedia.org/articles/x") == 3
    ranked = S.rank([{"url": "https://radiopaedia.org/a", "score": 0.9}, {"url": "https://pubs.rsna.org/b", "score": 0.5},
                     {"url": "https://pmc.ncbi.nlm.nih.gov/c", "score": 0.7}])
    assert [r["url"] for r in ranked] == ["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c", "https://radiopaedia.org/a"]


async def test_gather_dedupes_and_extracts_top_two(monkeypatch):
    calls = {"search": [], "extract": []}

    async def fake_search(q):
        calls["search"].append(q)
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.5, "content": "s"},
                {"url": "https://radiopaedia.org/a", "title": "A", "score": 0.9, "content": "s"},
                {"url": "https://pmc.ncbi.nlm.nih.gov/c", "title": "C", "score": 0.7, "content": "s"}]

    async def fake_extract(urls):
        calls["extract"].append(urls)
        return {u: f"text of {u}" for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, sources = await S.gather(["q1", "q2"], branch="Solid")
    assert calls["extract"] == [["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c"]]
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c"]
    assert chunks[0].branch == "Solid" and sources[0].tier == 1


async def test_gather_falls_back_to_search_content_when_extract_fails(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://x.org/a", "title": "A", "score": 0.5, "content": "search snippet text"}]

    async def fake_extract(urls):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert chunks[0].text == "search snippet text"
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_search.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the search module**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/search.py
"""Targeted search for one guideline (spec §5.3). Queries are built only from the guideline's identity, publication
and branch names, never from dictated words: the guideline's own vocabulary finds it best, the results serve every
later case, and no patient text reaches the search API."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from ...guideline_prefetch import DOMAIN_FILTER_PATHWAY, _normalize_tavily_results
from .types import Chunk, Publication, Source

logger = logging.getLogger(__name__)

EXTRACT_FOCUS = "categories, criteria, thresholds, required features, management recommendations"
TOP_URLS = 2
SEARCH_TIMEOUT_S = 15.0
EXTRACT_TIMEOUT_S = 30.0

# Tier 1: publishers and issuing societies. Tier 2: PubMed Central full text. Tier 3: everything else.
TIER1 = {*DOMAIN_FILTER_PATHWAY, "pubs.rsna.org", "rsna.org", "acr.org", "www.acr.org", "ajronline.org",
         "www.ajronline.org", "bir.org.uk", "esur.org", "www.esur.org", "eje.bioscientifica.com",
         "academic.oup.com", "uicc.org", "www.uicc.org", "thorax.bmj.com", "britishthyroidassociation.org",
         "www.britishthyroidassociation.org", "link.springer.com", "esmo.org", "www.esmo.org"}
TIER2 = {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"}


def _clean(s: str) -> str:
    return " ".join(re.sub(r"[·•|]+", " ", s).split())


def first_pass_queries(name: str, version: str, pub: Publication, branch: str) -> list[str]:
    ident = _clean(f"{name} {version}")
    q1 = f'"{pub.title}" {pub.year}'.strip() if pub.title else f"{ident} classification"
    q2 = _clean(f"{ident} {branch} criteria recommendations")
    return [q1, q2]


def branch_query(name: str, version: str, branch: str) -> str:
    return _clean(f"{name} {version} {branch} recommendations")


def tier(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    if host in TIER1 or any(host.endswith("." + d) for d in TIER1):
        return 1
    if host in TIER2:
        return 2
    return 3


def rank(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda r: (tier(r.get("url", "")), -float(r.get("score") or 0.0)))


async def _search(query: str) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    from tavily import AsyncTavilyClient
    try:
        resp = await asyncio.wait_for(AsyncTavilyClient(key).search(query=query, search_depth="basic", max_results=5),
                                      SEARCH_TIMEOUT_S)
        return _normalize_tavily_results(resp)
    except Exception as e:
        logger.warning("[copilot.search] %s: %s q=%r", type(e).__name__, str(e)[:160], query[:80])
        return []


async def _extract(urls: list[str]) -> dict[str, str]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key or not urls:
        return {}
    from tavily import AsyncTavilyClient
    try:
        resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(
            urls=urls, query=EXTRACT_FOCUS, chunks_per_source=5, extract_depth="advanced"), EXTRACT_TIMEOUT_S)
    except Exception as e:
        logger.warning("[copilot.extract] %s: %s", type(e).__name__, str(e)[:160])
        return {}
    return {r.get("url", ""): (r.get("raw_content") or "").strip() for r in resp.get("results", []) if r.get("url")}


async def gather(queries: list[str], branch: str) -> tuple[list[Chunk], list[Source]]:
    """Search every query in parallel, rank by source tier, extract the top URLs (focus query). A URL whose extract
    fails keeps its search content, so one blocked page never empties the pass."""
    found: dict[str, dict] = {}
    for results in await asyncio.gather(*(_search(q) for q in queries)):
        for r in results:
            found.setdefault(r["url"], r)
    top = rank(list(found.values()))[:TOP_URLS]
    if not top:
        return [], []
    extracted = await _extract([r["url"] for r in top])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks, sources = [], []
    for r in top:
        text = extracted.get(r["url"]) or r.get("content") or ""
        if text.strip():
            chunks.append(Chunk(url=r["url"], text=text, branch=branch))
            sources.append(Source(url=r["url"], title=r.get("title", ""), tier=tier(r["url"]), fetched_at=now))
    return chunks, sources
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_search.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/search.py backend/tests/test_copilot_search.py
git commit -m "feat(copilot): identity-only queries, source-tier ranking, Tavily gather"
```

---

### Task 5: Targeted fetch (`resolve_guideline`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/fetch.py`
- Test: `backend/tests/test_copilot_fetch.py`

The flow follows spec §5.3:
1. A registry hit with the card's branch checked returns at once.
2. Otherwise the first pass runs: gather with Q1 and Q2, then Jev coverage for the case's branch. Below the bar, one
   more query runs and coverage is asked again.
3. Structure the branch, check the evidence, upsert.
4. Fire the background fill for the other skeleton branches.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_fetch.py
import asyncio

from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import (Branch, Card, Chunk, GuidelineContent, Input, Output,
                                                         Publication, Source)

CARD = Card(key="fleischner@2017", name="Fleischner", version="2017", finding_id="u1",
            branch="Solid", skeleton=["Solid", "Subsolid"], publication=Publication(title="T", year="2017"))


def _branch(name, quote="no routine follow-up"):
    return Branch(name=name, inputs=[Input(id="risk", question="Risk", options=["Low", "High"])], rule="r",
                  outputs=[Output(when="<6 mm", classification="None", recommendation="No routine follow-up", quote=quote)])


def _stub(monkeypatch, cover=0.9, evidence=1.0, structured=None):
    calls = {"gather": [], "structure": []}

    async def gather(queries, branch, focus="", exclude=None):
        calls["gather"].append((queries, branch))
        return [Chunk(url="https://pubs.rsna.org/x", text="… No routine follow-up …", branch=branch)], \
               [Source(url="https://pubs.rsna.org/x", tier=1)]

    async def coverage(source, branches, transport=None):
        return {b: cover for b in branches}

    async def evidence_(source, claims, transport=None):
        return [evidence for _ in claims]

    async def structure(name, version, branch, text):
        calls["structure"].append(branch)
        return structured or F.Structured(summary="sum", applies_to="nodules", aliases=["fleischner society"],
                                          branch=_branch(branch))
    monkeypatch.setattr(F.S, "gather", gather)
    monkeypatch.setattr(F.J, "coverage", coverage)
    monkeypatch.setattr(F.J, "evidence", evidence_)
    monkeypatch.setattr(F, "_structure", structure)
    monkeypatch.setattr(F, "_spawn_fill", lambda *a, **k: None)
    return calls


async def test_first_pass_saves_checked_branch(db_session, monkeypatch):
    calls = _stub(monkeypatch)
    entry = await F.resolve_guideline(db_session, CARD)
    assert entry is not None and entry.content.branch("Solid").state == "checked"
    assert calls["gather"][0][0] == ['"T" 2017', "Fleischner 2017 Solid criteria recommendations"]
    assert entry.status == "draft" and entry.sources[0].tier == 1


async def test_registry_hit_makes_no_search(db_session, monkeypatch):
    R.upsert(db_session, key=CARD.key, name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[_branch("Solid").model_copy(update={"state": "checked"})]),
             sources=[], chunks=[])
    calls = _stub(monkeypatch)
    await F.resolve_guideline(db_session, CARD)
    assert calls["gather"] == []


async def test_low_coverage_runs_one_branch_query_then_not_available(db_session, monkeypatch):
    calls = _stub(monkeypatch, cover=0.2)
    entry = await F.resolve_guideline(db_session, CARD)
    assert len(calls["gather"]) == 2 and calls["gather"][1][0] == ["Fleischner 2017 Solid recommendations"]
    assert entry.content.branch("Solid").state == "not_available" and calls["structure"] == []


async def test_unsupported_outputs_are_dropped(db_session, monkeypatch):
    _stub(monkeypatch, evidence=0.1)
    entry = await F.resolve_guideline(db_session, CARD)
    assert entry.content.branch("Solid").state == "not_available"


async def test_no_results_returns_none_and_stores_nothing(db_session, monkeypatch):
    _stub(monkeypatch)

    async def empty(queries, branch, focus="", exclude=None):
        return [], []
    monkeypatch.setattr(F.S, "gather", empty)
    assert await F.resolve_guideline(db_session, CARD) is None
    assert R.by_key(db_session, CARD.key) is None


async def test_concurrent_resolves_share_one_fetch(db_session, monkeypatch):
    calls = _stub(monkeypatch)
    await asyncio.gather(F.resolve_guideline(db_session, CARD), F.resolve_guideline(db_session, CARD))
    assert len(calls["gather"]) == 1


def test_pending_branches_listed_for_fill():
    content = GuidelineContent(branches=[_branch("Solid").model_copy(update={"state": "checked"})])
    assert F.to_fill(["Solid", "Subsolid"], content) == ["Subsolid"]
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_fetch.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the fetch module**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/fetch.py
"""The targeted fetch (spec §5.3): source first, the case's branch first. Search by identity, Jev checks the
branch is covered, gpt-oss structures it with a quote per output, Jev checks every quote that is not an exact
match, the entry is upserted as a draft; the other skeleton branches fill in the background."""
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from . import jev as J
from . import registry as R
from . import search as S
from .types import Branch, Card, Chunk, Entry, GuidelineContent, Source

logger = logging.getLogger(__name__)

STRUCTURE_TIMEOUT_S = 30.0
_LOCKS: dict[str, asyncio.Lock] = {}
_FILLING: set[str] = set()
_TASKS: set[asyncio.Task] = set()

STRUCTURE_SYS = """You turn source text about one published radiology classification system or management guideline into a structured entry for ONE branch of it. Use only what the SOURCE states.
- branch.inputs: the features or facts the branch's decision needs (each with an id, a short question and its options exactly as the source names them; settled_by: how a radiology report would state it).
- branch.rule: the decision rule for this branch in compact plain text, citing every threshold, size band and interval exactly as the source states it.
- branch.outputs: one per category or recommendation the source gives for this branch: when (the condition over the inputs), classification (the category label the source uses, or "" when the branch only sets management), recommendation (the action or interval as the source states it, "" when none), quote (a verbatim span of the SOURCE, 5-40 words, that states this output).
- summary: two plain sentences on what the whole system is for. applies_to: one line on which findings it classifies. aliases: other names and abbreviations the source uses for the system.
Never add a threshold, interval or category the SOURCE does not state; leave a list empty rather than guess."""


class Structured(BaseModel):
    summary: str = ""
    applies_to: str = ""
    aliases: list[str] = Field(default_factory=list)
    branch: Branch


async def _structure(name: str, version: str, branch: str, text: str) -> Structured:
    prompt = f"SYSTEM: {name} {version}\nBRANCH: {branch}\n\nSOURCE:\n{text[:J.SOURCE_MAX]}"   # the cap Jev's windows cover
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=MODEL_CONFIG["GUIDELINE_PREFETCH"], output_type=Structured, system_prompt=STRUCTURE_SYS,
        user_prompt=prompt, api_key="", model_settings={"temperature": 0, "max_tokens": 6000,
                                                        "reasoning_effort": "low"}), STRUCTURE_TIMEOUT_S)
    return r.output


def _text(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.url}]\n{c.text}" for c in chunks)


def to_fill(skeleton: list[str], content: GuidelineContent) -> list[str]:
    done = {b.name for b in content.branches if b.state != "pending"}
    return [b for b in skeleton if b not in done]


async def _fetch_branch(card: Card, branch: str, queries: list[str]) -> tuple[Structured | None, Branch, list[Chunk], list[Source]]:
    """One branch: gather → coverage (one extra query below the bar) → structure → evidence."""
    chunks, sources = await S.gather(queries, branch, focus=branch)
    if not chunks:
        return None, Branch(name=branch, state="pending"), [], []
    cover = (await J.coverage(_text(chunks), [branch])).get(branch, 0.0)
    if cover < J.COVER_MIN:   # one retry on new pages only (review: the same URLs re-extract the same chunks)
        more, more_src = await S.gather([S.branch_query(card.name, card.version, branch)], branch, focus=branch,
                                        exclude={c.url for c in chunks})
        chunks, sources = chunks + more, sources + more_src
        cover = (await J.coverage(_text(chunks), [branch])).get(branch, 0.0) if more else cover
    if cover < J.COVER_MIN:
        return None, Branch(name=branch, state="not_available"), chunks, sources
    st = await _structure(card.name, card.version, branch, _text(chunks))
    claims = [(o.quote, f"{o.when} → {o.classification}; {o.recommendation}".strip()) for o in st.branch.outputs]
    scores = await J.evidence(_text(chunks), claims) if claims else []
    kept = [o for o, s in zip(st.branch.outputs, scores) if s >= J.EVIDENCE_MIN]
    b = st.branch.model_copy(update={"name": branch, "outputs": kept,
                                     "state": "checked" if kept else "not_available"})
    return st, b, chunks, sources


def _save(db: Session, card: Card, st: Structured | None, b: Branch, chunks, sources) -> None:
    R.upsert(db, key=card.key, name=card.name, version=card.version, aliases=(st.aliases if st else []) + [card.name],
             publication=card.publication if card.publication.title else None,
             content=GuidelineContent(summary=st.summary if st else "", applies_to=st.applies_to if st else "",
                                      branches=[b]), sources=sources, chunks=chunks)


async def resolve_guideline(db: Session, card: Card) -> Entry | None:
    """The entry with the card's branch resolved (checked or not_available), or None when nothing could be fetched.
    Never raises: a failure is logged and returns what the registry already holds (or None)."""
    row = R.by_key(db, card.key)
    if row is not None:
        b = R.entry(row).content.branch(card.branch)
        if b is not None and b.state != "pending" or not card.branch:
            _spawn_fill(card, R.entry(row).content)
            return R.entry(row)
    lock = _LOCKS.setdefault(card.key, asyncio.Lock())
    async with lock:
        db.expire_all()
        row = R.by_key(db, card.key)
        if row is not None and (b := R.entry(row).content.branch(card.branch)) is not None and b.state != "pending":
            return R.entry(row)
        try:
            st, b, chunks, sources = await _fetch_branch(
                card, card.branch, S.first_pass_queries(card.name, card.version, card.publication, card.branch))
        except Exception as e:
            logger.warning("[copilot.fetch] %s %s: %s", card.key, type(e).__name__, str(e)[:200])
            return R.entry(row) if row is not None else None
        if not chunks:
            return R.entry(row) if row is not None else None
        _save(db, card, st, b, chunks, sources)
    entry = R.entry(R.by_key(db, card.key))
    _spawn_fill(card, entry.content)
    return entry


def _spawn_fill(card: Card, content: GuidelineContent) -> None:
    rest = [b for b in to_fill(card.skeleton, content) if f"{card.key}|{b}" not in _FILLING]
    if not rest:
        return
    t = asyncio.get_running_loop().create_task(_fill(card, rest))
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)


async def _fill(card: Card, branches: list[str]) -> None:
    """Background: each remaining branch with its own query, saved as it finishes, in its own DB session. A failure
    leaves the branch pending; the next open retries it."""
    for b in branches:
        _FILLING.add(f"{card.key}|{b}")

    async def one(branch: str) -> None:
        try:
            st, br, chunks, sources = await _fetch_branch(card, branch, [S.branch_query(card.name, card.version, branch)])
            if chunks:
                with SessionLocal() as db:
                    _save(db, card, st, br, chunks, sources)
        except Exception as e:
            logger.warning("[copilot.fill] %s/%s %s: %s", card.key, branch, type(e).__name__, str(e)[:200])
        finally:
            _FILLING.discard(f"{card.key}|{branch}")
    await asyncio.gather(*(one(b) for b in branches))
```

Note on precedence: `if b is not None and b.state != "pending" or not card.branch` reads as
`(b is not None and b.state != "pending") or not card.branch`. That is intended: a card with no branch, such as one
from ask, is served from the registry as it stands. `SessionLocal` is exported by `database/__init__.py`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_fetch.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/fetch.py backend/tests/test_copilot_fetch.py
git commit -m "feat(copilot): targeted source-first fetch, branch-first with background fill"
```

---

### Task 5b: TNM provider (offline UICC TNM 9)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/tnm.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/fetch.py` (`resolve_guideline` returns the TNM entry for
  TNM keys)
- Test: `backend/tests/test_copilot_tnm.py`

The data is `resources/tnm_9th_clean.json` **v2.2**:
- category text cleaned by `scripts/tnm/clean_tnm_9th.py` (commit `aabba56`);
- clinical stage tables rebuilt and hand-checked by `scripts/tnm/rebuild_stage_tables.py` (commit `a21bf43`).

Each rebuilt site has `stage_tables: [{variant, verified, rows: [{stage, T: [...], N: [...], M: [...]}]}]`. The cells
are category lists, with `"Any"` for any. Oesophagus has two variants, squamous cell carcinoma and adenocarcinoma.
Sites without `stage_tables` propose T, N and M only. The lookup below is the same one the rebuild script verified;
keep the two identical.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_tnm.py
from rapid_reports_ai.hybrid_stack.copilot import tnm as N


def test_sites_closed_list_excludes_non_tnm():
    s = N.sites()
    assert "Lung" in s and "Kidney" in s and "Gastrointestinal Stromal Tumour (GIST)" in s
    assert not ({"Brain & Spinal Cord", "Hodgkin Lymphoma", "Non-Hodgkin Lymphomas", "Bone & Soft Tissues"} & set(s))


def test_keys_round_trip():
    k = N.key_for("Colon and Rectum")
    assert k == "tnm-colon-and-rectum@9" and N.is_tnm(k) and N.site_for(k) == "Colon and Rectum"
    assert N.site_for("fleischner@2017") is None and N.site_for("tnm-nowhere@9") is None


def test_entry_has_axes_with_x_first_and_is_verified():
    e = N.entry("Lung")
    b = e.content.branches[0]
    assert e.status == "verified" and e.version == "9" and b.state == "checked"
    opts = {i.id: i.options for i in b.inputs}
    assert opts["T"][0] == "TX" and "T1mi" in opts["T"] and opts["N"][0] == "NX" and opts["M"][0] == "MX"
    assert "histology" not in opts
    assert "T2b:" in b.rule and "Minimally invasive adenocarcinoma" in b.rule


def test_variant_site_asks_histology():
    opts = {i.id: i.options for i in N.entry("Oesophagus").content.branches[0].inputs}
    assert opts["histology"] == ["Squamous cell carcinoma", "Adenocarcinoma"]


def test_stage_lookup_against_the_rebuilt_tables():
    # Known UICC TNM 9 stages; the three v2.0 failures first.
    cases = [("Lung", "T2b", "N1", "M0", "Stage IIB"), ("Kidney", "T3a", "N1", "M0", "Stage III"),
             ("Colon and Rectum", "T4b", "N2b", "M0", "Stage IIIC"), ("Lung", "TX", "N0", "M0", "Occult carcinoma"),
             ("Lung", "T4", "N3", "M0", "Stage IIIC"), ("Lung", "TX", "NX", "M1c1", "Stage IVB"),
             ("Colon and Rectum", "T3", "N0", "M0", "Stage IIA"), ("Pancreas", "T2", "N0", "M0", "Stage IB"),
             ("Stomach", "T3", "N2", "M0", "Stage III")]
    for site, t, n, m, want in cases:
        assert N.stage(site, "", t, n, m) == want, (site, t, n, m)
    assert N.stage("Lung", "", "TX", "N1", "M0") is None            # X matches only a listed X or "Any"
    assert N.stage("Oesophagus", "Adenocarcinoma", "T1", "N1", "M0") == "Stage IIA"
    assert N.stage("Oesophagus", "Squamous cell carcinoma", "T1", "N1", "M0") == "Stage I"
    assert N.stage("Oesophagus", "", "T1", "N1", "M0") is None      # histology needed
    assert N.stage("Prostate", "", "T2", "N0", "M0") is None        # no verified table


def test_proposal_built_in_code():
    p = N.proposal("Lung", {"T": "T2b", "N": "N1", "M": "M0"})
    assert p.classification == "cT2b N1 M0, Stage IIB (UICC TNM 9th)"
    assert p.line == "Staging (UICC TNM 9th): cT2b N1 M0, Stage IIB."
    assert N.proposal("Prostate", {"T": "T2", "N": "N0", "M": "M0"}).line == "Staging (UICC TNM 9th): cT2 N0 M0."
    assert N.proposal("Lung", {"T": "T2b", "N": "N1"}) is None       # every axis must be answered
    assert N.proposal("Oesophagus", {"T": "T1", "N": "N1", "M": "M0"}) is None   # and histology where tables vary
    assert N.proposal("Oesophagus", {"T": "T1", "N": "N1", "M": "M0", "histology": "Adenocarcinoma"}).line.endswith("Stage IIA.")


def test_material_for_ask():
    assert "AUTHORITATIVE TNM REFERENCE" in N.material("Lung")
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_tnm.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the provider**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/tnm.py
"""UICC TNM 9th edition as a Copilot provider (spec §5.8): offline (resources/tnm_9th_clean.json v2.2), verified by
provenance, no fetch. One branch with T, N and M inputs (X first: the reporting convention for an axis that cannot
be assessed), plus histology where a site's stage table varies by it. The proposal is assembled in code; the stage
comes from the rebuilt, hand-checked stage_tables (scripts/tnm/rebuild_stage_tables.py: keep lookup identical)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ...tnm_lookup import TnmResult, format_tnm_evidence
from .registry import slug
from .types import Branch, Entry, GuidelineContent, Input, Output, Proposal, Publication, Source

DATA = Path(__file__).resolve().parents[2] / "resources" / "tnm_9th_clean.json"
EXCLUDED = {"Brain & Spinal Cord", "Hodgkin Lymphoma", "Non-Hodgkin Lymphomas"}
X = {"T": "TX", "N": "NX", "M": "MX"}
TAG = "UICC TNM 9th"
SOURCE = "UICC TNM Classification of Malignant Tumours, 9th edition (offline)"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text())["tumours"]


def sites() -> list[str]:
    return [s for s, r in _data().items() if s not in EXCLUDED and any(r["tnm"].get(a) for a in "TNM")]


def key_for(site: str) -> str:
    return f"tnm-{slug(site)}@9"


def is_tnm(key: str) -> bool:
    return key.startswith("tnm-")


def site_for(key: str) -> str | None:
    return next((s for s in sites() if key_for(s) == key), None)


def _tables(site: str) -> list[dict]:
    return [t for t in _data()[site].get("stage_tables") or [] if t.get("verified")]


def variants(site: str) -> list[str]:
    return [t["variant"] for t in _tables(site) if t["variant"]]


def _options(site: str, axis: str) -> list[str]:
    cats = list((_data()[site]["tnm"].get(axis) or {}).keys())
    return cats if X[axis] in cats else [X[axis], *cats]


def _result(site: str) -> TnmResult:
    r = _data()[site]
    return TnmResult(tumour=site, icd_o=r.get("icd_o", ""), edition_uicc="9th", edition_ajcc=None,
                     tnm_json={a: r["tnm"].get(a) or {} for a in "TNM"},
                     stage_grouping=[{"stage": g["stage"], **{a: ", ".join(g[a]) for a in "TNM"}}
                                     for t in _tables(site) for g in t["rows"]],
                     rules=r.get("rules", ""), rrf_score=1.0)


def material(site: str) -> str:
    return format_tnm_evidence(_result(site))


def entry(site: str) -> Entry:
    r = _data()[site]
    inputs = [Input(id=a, question=f"{a} category", options=_options(site, a)) for a in "TNM"]
    if variants(site):
        inputs.append(Input(id="histology", question="Histology", options=variants(site)))
    rule = "\n".join(f"{k}: {v}" for a in "TNM" for k, v in (r["tnm"].get(a) or {}).items())
    outputs = [Output(when=f"{t['variant'] + ': ' if t['variant'] else ''}{', '.join(g['T'])} | {', '.join(g['N'])} | "
                           f"{', '.join(g['M'])}", classification=g["stage"],
                      quote=f"{g['stage']}: {' '.join(g['T'])} {' '.join(g['N'])} {' '.join(g['M'])}")
               for t in _tables(site) for g in t["rows"]]
    return Entry(key=key_for(site), name=f"TNM {site}", version="9", status="verified",
                 publication=Publication(title=SOURCE, body="UICC", year="2025"),
                 content=GuidelineContent(applies_to=(r.get("rules") or "").split(". ")[0],
                                          summary=f"{TAG} staging of {site.lower()} tumours.",
                                          branches=[Branch(name="Staging", state="checked", inputs=inputs, rule=rule,
                                                           outputs=outputs)]),
                 sources=[Source(url="", title=SOURCE, tier=1)])


def _matches(cat: str, cells: list[str]) -> int:
    """2: exact cell; 1: 'Any' or the cell is its parent (T2b under 'T2'); 0: no match. An X category matches only a
    cell that lists it (Lung 'Occult carcinoma TX N0 M0') or 'Any'."""
    if cat in cells:
        return 2
    if "Any" in cells:
        return 1
    if cat.endswith("X"):
        return 0
    return 1 if any(cat.startswith(c) for c in cells) else 0


def lookup(rows: list[dict], t: str, n: str, m: str) -> str | None:
    hits = []
    for g in rows:
        s = [_matches(c, g[a]) for c, a in ((t, "T"), (n, "N"), (m, "M"))]
        if all(s):
            hits.append((sum(s), g["stage"]))
    if not hits:
        return None
    best = max(h for h, _ in hits)
    stages = {st for h, st in hits if h == best}
    stages = {st for st in stages if not any(o != st and o.startswith(st) for o in stages)}   # IIA over II
    return stages.pop() if len(stages) == 1 else None


def stage(site: str, variant: str, t: str, n: str, m: str) -> str | None:
    tables = _tables(site)
    if len(tables) > 1:
        tables = [x for x in tables if x["variant"] == variant]
    return lookup(tables[0]["rows"], t, n, m) if len(tables) == 1 else None


def proposal(site: str, settled: dict[str, str]) -> Proposal | None:
    if any(not settled.get(a) for a in "TNM") or (variants(site) and settled.get("histology") not in variants(site)):
        return None
    tnm = f"c{settled['T']} {settled['N']} {settled['M']}"
    st = stage(site, settled.get("histology", ""), settled["T"], settled["N"], settled["M"])
    text = f"{tnm}, {st}" if st else tnm
    return Proposal(classification=f"{text} ({TAG})", line=f"Staging ({TAG}): {text}.")
```

In `fetch.py`, at the top of `resolve_guideline`:

```python
    from . import tnm
    if tnm.is_tnm(card.key):
        site = tnm.site_for(card.key)
        return tnm.entry(site) if site else None
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_tnm.py tests/test_copilot_fetch.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/tnm.py backend/src/rapid_reports_ai/hybrid_stack/copilot/fetch.py backend/tests/test_copilot_tnm.py
git commit -m "feat(copilot): offline UICC TNM 9 provider — X convention, histology variants, verified stage tables"
```

---

### Task 6: Matcher

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py`
- Test: `backend/tests/test_copilot_matcher.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_matcher.py
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, GuidelineContent

U = [M.Finding(id="u1", text="8 mm part-solid nodule right upper lobe."), M.Finding(id="u2", text="Simple renal cyst.")]


def _raw(**per):
    return M.RawMatch(findings=[M.RawFinding(id=k, systems=v) for k, v in per.items()])


def _sys(name, version="2017", branch="Subsolid", skeleton=("Solid", "Subsolid")):
    return M.RawSystem(name=name, version=version, why="w", branch=branch, skeleton=list(skeleton),
                       publication=M.Publication(title="T", year=version))


async def test_new_candidate_becomes_new_key(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT chest", "", U)
    assert [(c.key, c.finding_id, c.branch, c.known) for c in cards] == [("fleischner@2017", "u1", "Subsolid", False)]


async def test_alias_hit_uses_registry_key_and_branches(db_session, monkeypatch):
    M.clear_cache()
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=["fleischner society"],
             publication=None, content=GuidelineContent(branches=[Branch(name="Solid"), Branch(name="Subsolid nodule")]),
             sources=[], chunks=[])

    async def call(prompt):
        assert "fleischner@2017" in prompt          # the known registry names are offered
        return _raw(u1=[_sys("Fleischner Society", "2017")])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", U[:1])
    assert cards[0].key == "fleischner@2017" and cards[0].known and cards[0].skeleton == ["Solid", "Subsolid nodule"]
    assert cards[0].branch == "Subsolid nodule"          # the registry's branch name, not the model's


async def test_two_versions_go_to_jev(db_session, monkeypatch):
    M.clear_cache()
    for v in ("2005", "2017"):
        R.upsert(db_session, key=f"fleischner@{v}", name="Fleischner", version=v, aliases=[], publication=None,
                 content=GuidelineContent(), sources=[], chunks=[])

    async def call(prompt):
        return _raw(u1=[_sys("Fleischner", "")])

    async def pick(finding, name, rows):
        return "fleischner@2017"
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_jev_pick", pick)
    assert (await M.match(db_session, "CT", "", U[:1]))[0].key == "fleischner@2017"


async def test_cache_skips_model_for_unchanged_findings(db_session, monkeypatch):
    M.clear_cache()
    n = {"calls": 0}

    async def call(prompt):
        n["calls"] += 1
        return _raw(u1=[_sys("Fleischner")], u2=[])
    monkeypatch.setattr(M, "_call", call)
    await M.match(db_session, "CT", "", U)
    await M.match(db_session, "CT", "", U)
    assert n["calls"] == 1


async def test_caps(db_session, monkeypatch):
    M.clear_cache()
    many = [M.Finding(id=f"u{i}", text=f"finding {i}") for i in range(5)]

    async def call(prompt):
        return _raw(**{f.id: [_sys(f"Sys{f.id}a"), _sys(f"Sys{f.id}b"), _sys(f"Sys{f.id}c")] for f in many})
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT", "", many)
    assert len(cards) == M.MAX_PER_CASE
    assert max(sum(c.finding_id == f.id for c in cards) for f in many) <= M.MAX_PER_FINDING


async def test_tnm_candidate_needs_listed_site_and_jev_gate(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        assert "TNM SITES:" in prompt and "- Lung" in prompt
        return _raw(u1=[M.RawSystem(name="TNM", version="9", site="Lung", why="primary lung mass")],
                    u2=[M.RawSystem(name="TNM", version="9", site="Lungs", why="not on the list")])
    gate = {"Lung": 0.9}

    async def tnm_gate(finding, site):
        return gate[site]
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    cards = await M.match(db_session, "CT", "", U)
    assert [(c.key, c.status, c.branch) for c in cards] == [("tnm-lung@9", "verified", "Staging")]
    M.clear_cache()
    gate["Lung"] = 0.2
    assert await M.match(db_session, "CT", "", U) == []


async def test_model_failure_returns_no_cards(db_session, monkeypatch):
    M.clear_cache()

    async def call(prompt):
        raise RuntimeError("down")
    monkeypatch.setattr(M, "_call", call)
    assert await M.match(db_session, "CT", "", U) == []
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_matcher.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the matcher**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py
"""The matcher (spec §5.2): which published systems apply to each dictated abnormal finding, from model knowledge.
It also returns each system's publication and skeleton (branch names, never thresholds) and the branch this finding
falls into: the one case-aware output, which decides what the targeted fetch reads first."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from ...jev_client import JEV_MODEL, jev_post
from ..schemas import scan_key
from . import registry as R
from . import tnm
from .types import Card, Publication

logger = logging.getLogger(__name__)

TNM_GATE_MIN = 0.7   # provisional: Jev "a primary malignancy of this site that would be staged"; set by the Task 13 lab
MAX_PER_FINDING = 2
MAX_PER_CASE = 6
TIMEOUT_S = 8.0
PICK_MIN = 0.6
_CACHE: "OrderedDict[tuple, list]" = OrderedDict()
_CACHE_MAX = 512

MATCH_SYS = """You recognise which published radiology classification systems, scoring systems, staging systems or management guidelines apply to findings a radiologist has dictated. Practice is in the UK: where several systems exist for the same finding, prefer the one used in UK radiology.

For each FINDING, list 0-2 systems a radiologist would apply to THAT finding on THIS scan, most useful first:
- only a system that classifies, scores, stages or sets the management of this finding as described: the finding already has the features the system works on (a size, a morphology, a density or signal, an enhancement pattern, a location), or is the kind of finding the system exists for;
- never a system for a different finding, for a diagnosis the dictation does not make, or a general reporting standard;
- most findings have none: return an empty list for them.
Each system:
- name: its usual name, without the version; when KNOWN SYSTEMS lists it, exactly that name
- version: the edition or year ("" if it has none); when KNOWN SYSTEMS lists it, that version
- why: one short clause, what about the finding makes it apply
- publication: the defining publication's title, issuing body and year, as best you know them (never a URL)
- skeleton: the system's branches or categories by name only (the groups its rules are organised by), never thresholds or intervals
- branch: the skeleton branch this finding falls into ("" when the finding does not yet say enough to tell)
- site: "" except for TNM staging
TNM STAGING: for a primary malignant tumour (known or suspected) that would be staged, list name "TNM", version "9", site = exactly one name from TNM SITES, skeleton ["Staging"], branch "Staging". Never TNM for a metastasis, a benign lesion or an indeterminate incidental finding."""


class Finding(BaseModel):
    id: str
    text: str


class RawSystem(BaseModel):
    name: str = ""
    version: str = ""
    site: str = ""
    why: str = ""
    publication: Publication = Field(default_factory=Publication)
    skeleton: list[str] = Field(default_factory=list)
    branch: str = ""


class RawFinding(BaseModel):
    id: str
    systems: list[RawSystem] = Field(default_factory=list)


class RawMatch(BaseModel):
    findings: list[RawFinding] = Field(default_factory=list)


def clear_cache() -> None:
    _CACHE.clear()


def _prompt(scan_type: str, history: str, findings: list[Finding], known: list[tuple[str, str, str]]) -> str:
    s = f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n"
    s += "\n".join(f"- [{f.id}] {f.text}" for f in findings)
    if known:
        s += "\n\nKNOWN SYSTEMS (key: name version):\n" + "\n".join(f"- {k}: {n} {v}".rstrip() for k, n, v in known)
    s += "\n\nTNM SITES:\n" + "\n".join(f"- {x}" for x in tnm.sites())
    return s


async def _call(prompt: str) -> RawMatch:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=MODEL_CONFIG["GUIDELINE_PREFETCH"], output_type=RawMatch, system_prompt=MATCH_SYS,
        user_prompt=prompt, api_key="", model_settings={"temperature": 0, "max_tokens": 4000,
                                                        "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def _jev_pick(finding: str, name: str, rows) -> str | None:
    """Several registry versions of one system: Jev chooses between distinct entries, or none."""
    crit = {r.key: f"{r.name} {r.version}".strip() for r in rows}
    crit["none"] = "None of these editions applies."
    q = {"type": "choice", "instructions": f"Which edition of {name} should be applied to the FINDING?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": f"FINDING:\n{finding}", "questions": {"pick": q}},
                       os.environ.get("OPENROUTER_API_KEY", ""), 4.0)
    r.raise_for_status()
    a = r.json()["answers"]["pick"]
    return a["choice"] if a["choice"] != "none" and float(a.get("confidence") or 0) >= PICK_MIN else None


def _same_branch(branch: str, skeleton: list[str]) -> str:
    """The registry's own name for the model's branch: exact, then one contains the other; else the model's name
    (a new branch, fetched on open)."""
    if branch in skeleton or not skeleton:
        return branch
    nb = R.norm(branch)
    hits = [b for b in skeleton if nb and (nb in R.norm(b) or R.norm(b) in nb)]
    if len(hits) == 1:
        return hits[0]
    return skeleton[0] if len(skeleton) == 1 else branch


async def _tnm_gate(finding: str, site: str) -> float:
    q = {"type": "noul", "instructions": (f"The FINDING describes a primary malignant tumour (known or suspected) of this "
                                          f"site that would be staged: {site}")}
    r = await jev_post({"model": JEV_MODEL, "state": f"FINDING:\n{finding}", "questions": {"q": q}},
                       os.environ.get("OPENROUTER_API_KEY", ""), 4.0)
    r.raise_for_status()
    return float(((r.json().get("answers") or {}).get("q") or {}).get("noul") or 0.0)


async def _tnm_card(f: Finding, s: RawSystem) -> Card | None:
    """A TNM candidate: the site must be on the closed list and pass the Jev gate (fails closed: no card)."""
    if s.site not in tnm.sites():
        return None
    try:
        if await _tnm_gate(f.text, s.site) < TNM_GATE_MIN:
            return None
    except Exception:
        return None
    e = tnm.entry(s.site)
    return Card(key=e.key, name=e.name, version="9", finding_id=f.id, why=s.why, branch="Staging",
                skeleton=["Staging"], publication=e.publication, known=True, status="verified")


async def _card(db: Session, f: Finding, s: RawSystem) -> Card | None:
    if not s.name.strip():
        return None
    if s.name.strip().upper() == "TNM":
        return await _tnm_card(f, s)
    key = R.make_key(s.name, s.version)
    row = R.by_key(db, key)
    if row is None:
        rows = R.by_alias(db, s.name)
        if len(rows) == 1 and (not s.version or rows[0].version == s.version or not rows[0].version):
            row = rows[0]
        elif len(rows) > 1:
            try:
                picked = await _jev_pick(f.text, s.name, rows)
            except Exception:
                picked = None
            row = R.by_key(db, picked) if picked else None
    if row is not None:
        e = R.entry(row)
        skeleton = [b.name for b in e.content.branches] or s.skeleton
        branch = _same_branch(s.branch, skeleton)
        return Card(key=e.key, name=e.name, version=e.version, finding_id=f.id, why=s.why, branch=branch,
                    skeleton=skeleton, publication=e.publication if e.publication.title else s.publication,
                    known=True, status=e.status)
    return Card(key=key, name=s.name.strip(), version=s.version.strip(), finding_id=f.id, why=s.why, branch=s.branch,
                skeleton=s.skeleton, publication=s.publication, known=False, status="new")


async def match(db: Session, scan_type: str, history: str, findings: list[Finding]) -> list[Card]:
    """Cards for these findings, ranked and capped. Only findings whose text the cache has not seen call the model.
    Fails open: no cards."""
    sk = scan_key(scan_type)
    keyf = lambda f: (sk, R.norm(f.text))
    todo = [f for f in findings if keyf(f) not in _CACHE]
    if todo:
        try:
            raw = await _call(_prompt(scan_type, history, todo, R.known(db)))
        except Exception as e:
            logger.warning("[copilot.match] %s: %s", type(e).__name__, str(e)[:200])
            return []
        got = {rf.id: rf.systems for rf in raw.findings}
        for f in todo:
            _CACHE[keyf(f)] = got.get(f.id, [])
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    cards: list[Card] = []
    for f in findings:
        per = 0
        for s in _CACHE.get(keyf(f), []):
            if per >= MAX_PER_FINDING or len(cards) >= MAX_PER_CASE:
                break
            c = await _card(db, f, s)
            if c is not None and all(x.id != c.id for x in cards):
                cards.append(c)
                per += 1
    return cards
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_matcher.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py backend/tests/test_copilot_matcher.py
git commit -m "feat(copilot): matcher with skeleton, case branch, registry normalisation and caps"
```

---

### Task 7: Preview and the numeric guard

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/preview.py`
- Test: `backend/tests/test_copilot_preview.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_preview.py
from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot.types import (Branch, Entry, GuidelineContent, Input, Output, Preview,
                                                         Proposal, Settled)

BR = Branch(name="Solid", state="checked", inputs=[Input(id="risk", question="Risk", options=["Low risk", "High risk"])],
            rule="Solid 6-8 mm: high risk CT at 6-12 months, then 18-24 months",
            outputs=[Output(when="6-8 mm, high risk", classification="", recommendation="CT at 6-12 months, then CT at 18-24 months", quote="q")])
ENTRY = Entry(key="fleischner@2017", name="Fleischner", version="2017", content=GuidelineContent(branches=[BR]))


def test_numbers_ok():
    p = Proposal(classification="Fleischner 2017", line="7 mm solid nodule; Fleischner 2017 high risk.",
                 recommendation="CT at 6-12 months, then CT at 18-24 months")
    assert P.numbers_ok(p, ENTRY, BR, "7 mm solid nodule")
    bad = p.model_copy(update={"recommendation": "CT at 3 months"})
    assert not P.numbers_ok(bad, ENTRY, BR, "7 mm solid nodule")


def test_validate_forces_answers_and_drops_bad_values():
    raw = Preview(settled=[Settled(input="risk", value="Medium"), Settled(input="ghost", value="x")],
                  missing=["risk", "ghost"],
                  proposal=Proposal(classification="c", line="l"))
    out = P.validate(raw, BR, answered={})
    assert out.settled == [] and out.missing == ["risk"] and out.proposal is None
    out2 = P.validate(Preview(missing=["risk"]), BR, answered={"risk": "High risk"})
    assert out2.settled[0].value == "High risk" and out2.missing == []


async def test_preview_not_checked_branch_has_no_proposal():
    nb = BR.model_copy(update={"state": "not_available"})
    e = ENTRY.model_copy(update={"content": GuidelineContent(branches=[nb])})
    out = await P.preview(e, "Solid", "7 mm solid nodule.", "", {})
    assert out.proposal is None and out.missing == []


async def test_preview_drops_proposal_with_foreign_number(monkeypatch):
    async def call(prompt):
        return Preview(settled=[Settled(input="risk", value="High risk", quote="smoker")],
                       proposal=Proposal(classification="Fleischner 2017", line="l", recommendation="CT at 3 months"))
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert out.proposal is None and out.settled[0].value == "High risk"


async def test_tnm_preview_proposal_comes_from_code(monkeypatch):
    from rapid_reports_ai.hybrid_stack.copilot import tnm
    e = tnm.entry("Lung")

    async def call(prompt):
        assert "TX" in prompt
        return Preview(settled=[Settled(input="T", value="T2b"), Settled(input="N", value="N1"), Settled(input="M", value="M0")],
                       proposal=Proposal(classification="Stage IIB", line="model text"))
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(e, "Staging", "4.5 cm right upper lobe mass with ipsilateral hilar node.", "", {})
    assert out.proposal.line == "Staging (UICC TNM 9th): cT2b N1 M0, Stage IIB."


async def test_preview_failure_returns_empty(monkeypatch):
    async def call(prompt):
        raise RuntimeError("x")
    monkeypatch.setattr(P, "_call", call)
    assert (await P.preview(ENTRY, "Solid", "f", "", {})).proposal is None
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_preview.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the preview module**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/preview.py
"""The preview (spec §5.4): one checked branch applied to this case. Never stored. A proposal exists only when every
required input is settled, and every number in it must come from the branch, the entry's identity or the findings
(the numeric guard): a threshold the entry does not hold never reaches a card."""
from __future__ import annotations

import asyncio
import logging
import re

from ...enhancement_utils import _run_agent_with_model
from ...report_reconcile import QWEN
from .types import Branch, Entry, Preview, Proposal, Settled

logger = logging.getLogger(__name__)

TIMEOUT_S = 10.0
_NUM = re.compile(r"\d+(?:\.\d+)?")

PREVIEW_SYS = """You apply one branch of a published radiology classification system or guideline to a radiologist's dictated finding. ENTRY gives the branch's inputs, decision rule and outputs: use nothing else for criteria, thresholds, categories or recommendations.
1. settled: each ENTRY input that the FINDINGS or CLINICAL HISTORY already answer, with value = exactly one of that input's options and quote = the shortest verbatim span that settles it. Inputs listed under ANSWERED are settled by the radiologist: use them as given.
2. missing: the ids of the inputs the decision still needs that nothing settles (an input the decision does not need for this finding is neither settled nor missing).
3. proposal: only when missing is empty, otherwise null:
   - classification: "<system> <version>" followed by the ENTRY output's category label when it has one
   - line: one report sentence stating the classification for this finding (name the system and version; no recommendation, no interval)
   - recommendation: the ENTRY output's recommendation worded for this finding, "" when the output has none
An axis or input the FINDINGS say cannot be assessed on this scan is settled with its X option (TX, NX, MX) when the input offers one.
Never invent an input, option, category, threshold or interval the ENTRY does not contain."""


def _entry_text(e: Entry, b: Branch) -> str:
    ins = "\n".join(f"- {i.id}: {i.question} [{' | '.join(i.options)}]" for i in b.inputs)
    outs = "\n".join(f"- when {o.when}: {o.classification} | {o.recommendation}" for o in b.outputs)
    return f"SYSTEM: {e.name} {e.version}\nBRANCH: {b.name}\nINPUTS:\n{ins or '(none)'}\nRULE: {b.rule}\nOUTPUTS:\n{outs}"


def numbers_ok(p: Proposal, e: Entry, b: Branch, findings: str) -> bool:
    allowed_text = " ".join([e.name, e.version, b.rule, findings,
                             *(f"{o.when} {o.classification} {o.recommendation}" for o in b.outputs),
                             *(" ".join(i.options) for i in b.inputs)])
    allowed = set(_NUM.findall(allowed_text))
    return all(n in allowed for n in _NUM.findall(f"{p.classification} {p.line} {p.recommendation}"))


def validate(raw: Preview, b: Branch, answered: dict[str, str]) -> Preview:
    """Keep only settled values that are real options of real inputs; the radiologist's answers win; a proposal
    stands only when nothing required is missing."""
    opts = {i.id: i.options for i in b.inputs}
    settled = {s.input: s for s in raw.settled if s.input in opts and s.value in opts[s.input]}
    for k, v in answered.items():
        if k in opts and v in opts[k]:
            settled[k] = Settled(input=k, value=v, quote="")
    missing = [m for m in dict.fromkeys(raw.missing) if m in opts and m not in settled]
    return Preview(settled=list(settled.values()), missing=missing, proposal=raw.proposal if not missing else None)


async def _call(prompt: str) -> Preview:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=Preview, system_prompt=PREVIEW_SYS, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def preview(e: Entry, branch: str, findings: str, history: str, answered: dict[str, str]) -> Preview:
    b = e.content.branch(branch)
    if b is None or b.state != "checked":
        return Preview()
    answered_txt = "\n".join(f"- {k}: {v}" for k, v in answered.items()) or "(none)"
    prompt = (f"ENTRY:\n{_entry_text(e, b)}\n\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}"
              f"\n\nANSWERED:\n{answered_txt}")
    try:
        raw = await _call(prompt)
    except Exception as ex:
        logger.warning("[copilot.preview] %s: %s", type(ex).__name__, str(ex)[:200])
        return Preview(missing=[i.id for i in b.inputs if i.id not in answered])
    out = validate(raw, b, answered)
    from . import tnm
    if tnm.is_tnm(e.key):   # TNM: the model only settles axes; code assembles the proposal (and any stage)
        site = tnm.site_for(e.key)
        prop = tnm.proposal(site, {s.input: s.value for s in out.settled}) if site and not out.missing else None
        return out.model_copy(update={"proposal": prop})
    if out.proposal is not None and not numbers_ok(out.proposal, e, b, findings):
        logger.info("[copilot.preview] proposal dropped by the numeric guard (%s)", e.key)
        out = out.model_copy(update={"proposal": None})
    return out
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_preview.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/preview.py backend/tests/test_copilot_preview.py
git commit -m "feat(copilot): per-case preview with input validation and numeric guard"
```

---

### Task 8: Ask

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/ask.py`
- Test: `backend/tests/test_copilot_ask.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_ask.py
from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Card, Chunk, GuidelineContent, Output, Source

CTX = A.Context(scan_type="CT chest", history="", findings="7 mm solid nodule.")


def _seed(db):
    R.upsert(db, key="fleischner@2017", name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Solid", state="checked", outputs=[Output(classification="c", quote="q")])]),
             sources=[], chunks=[Chunk(url="https://a", text="perifissural nodules need no follow-up")])


async def test_card_scope_answered_from_material(db_session, monkeypatch):
    _seed(db_session)

    async def answers(material, q, transport=None):
        assert "perifissural" in material
        return 0.9

    async def grounded(question, material, ctx, history):
        return "No follow-up for typical perifissural nodules."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Does a perifissural shape change this?", "fleischner@2017", CTX, [])
    assert res.kind == "card" and res.key == "fleischner@2017" and "perifissural" in res.answer and not res.searched


async def test_card_scope_gap_searches_and_adds_supplement(db_session, monkeypatch):
    _seed(db_session)
    scores = iter([0.1, 0.9])

    async def answers(material, q, transport=None):
        return next(scores)

    async def phrase(question, name, version):
        return "Fleischner 2017 calcified nodule"

    async def gather(queries, branch, focus="", exclude=None):
        assert queries == ["Fleischner 2017 calcified nodule"]
        return [Chunk(url="https://b", text="benign calcification needs no follow-up")], [Source(url="https://b")]

    async def grounded(question, material, ctx, history):
        return "Benign calcification needs no follow-up."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Does calcification matter?", "fleischner@2017", CTX, [])
    assert res.searched and res.supported
    e = R.entry(R.by_key(db_session, "fleischner@2017"))
    assert e.content.supplements[0].question == "Does calcification matter?"


async def test_card_scope_gap_unanswered_says_so(db_session, monkeypatch):
    _seed(db_session)

    async def answers(material, q, transport=None):
        return 0.1

    async def phrase(question, name, version):
        return "x"

    async def gather(queries, branch, focus="", exclude=None):
        return [], []

    async def general(question, ctx, history):
        return "General answer."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A, "_general_answer", general)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert not res.supported and res.answer.startswith(A.NOT_IN_GUIDELINE)


def test_safe_phrase_drops_case_text():
    assert A._safe_phrase("Fleischner 2017 calcified nodule", "Fleischner", "2017") == "Fleischner 2017 calcified nodule"
    assert A._safe_phrase("Fleischner 7 mm nodule left lower lobe", "Fleischner", "2017") == "Fleischner 2017"


async def test_no_scope_general(db_session, monkeypatch):
    async def route(question, ctx, history):
        return A.RawRoute(guideline="", version="", answer="Up to about 10 mm.")
    monkeypatch.setattr(A, "_route", route)
    res = await A.ask(db_session, "Normal CBD post-cholecystectomy?", None, CTX, [])
    assert res.kind == "general" and res.answer == "Up to about 10 mm." and res.card is None


async def test_no_scope_guideline_resolves_card(db_session, monkeypatch):
    _seed(db_session)

    async def route(question, ctx, history):
        return A.RawRoute(guideline="Fleischner", version="2017", answer="")

    async def resolve(db, card):
        return R.entry(R.by_key(db, card.key))

    async def answers(material, q, transport=None):
        return 0.9

    async def grounded(question, material, ctx, history):
        return "Answer."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "How do I follow up this nodule?", None, CTX, [], finding_id="u1")
    assert res.kind == "card" and res.card.key == "fleischner@2017" and res.card.finding_id == "u1"
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_ask.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the ask module**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/ask.py
"""Ask (spec §5.5), written as structured steps rather than native tool use. With a card in scope: Jev decides
whether the stored material answers the question; if not, one targeted query within that guideline (phrased in its
own vocabulary, no case details), and a supported answer is kept as a supplement. With no card: route the question
to a guideline (resolved like a matched card) or answer it as a general question."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...enhancement_utils import _run_agent_with_model
from ...report_reconcile import QWEN
from . import jev as J
from . import registry as R
from . import search as S
from .fetch import resolve_guideline
from .types import Card, Entry, GuidelineContent, Supplement

logger = logging.getLogger(__name__)

TIMEOUT_S = 12.0
NOT_IN_GUIDELINE = "The guideline does not address this."

ROUTE_SYS = """A radiologist reporting a scan asks you a question. Decide what it is about.
- When answering it means applying, classifying, staging, scoring or managing something with a published radiology classification system or guideline (named or implied), set guideline to that system's usual name and version to its edition or year ("" if none), and leave answer empty: it is answered from the guideline itself.
- Otherwise set guideline to "" and answer in 2-4 plain sentences of British English, using the CASE for context. Say when something is uncertain or varies by local practice."""

GROUNDED_SYS = """Answer a radiologist's question about one published guideline in 2-4 plain sentences of British English. Use only the MATERIAL for any criterion, category, threshold or interval, and say which part of the guideline it comes from. Use the CASE only to make the answer specific. If the MATERIAL does not answer the question, say so in one sentence."""

PHRASE_SYS = """Write one web search phrase (at most 10 words) that would find the part of the named guideline answering the radiologist's question. Use the guideline's name, version and its own terms; never patient details, ages, sizes, measurements, sides, dates or anything specific to the case. Reply with the phrase only."""
_CASEY = re.compile(r"\d|\b(left|right|bilateral|year[- ]old|yo|male|female|patient)\b", re.I)


def _safe_phrase(phrase: str, name: str, version: str) -> str:
    """The search API never sees case text (spec §2.18): a phrase carrying digits other than the version, sides or
    demographics falls back to the guideline's identity alone."""
    rest = phrase.replace(version, "") if version else phrase
    return f"{name} {version}".strip() if _CASEY.search(rest) else phrase

GENERAL_SYS = """Answer a radiologist's question in 2-3 plain sentences of British English from general radiology knowledge, using the CASE for context. Say when something is uncertain or varies by local practice."""


class Context(BaseModel):
    scan_type: str = ""
    history: str = ""
    findings: str = ""


class QA(BaseModel):
    question: str
    answer: str


class RawRoute(BaseModel):
    guideline: str = ""
    version: str = ""
    answer: str = ""


class AskResult(BaseModel):
    kind: Literal["card", "general"]
    answer: str
    key: str | None = None
    card: Card | None = None
    entry: Entry | None = None
    searched: bool = False        # a targeted query ran for this question
    supported: bool = True        # the answer is grounded in guideline material
    error: str | None = None


def _ctx(ctx: Context, history: list[QA]) -> str:
    s = f"CASE:\nScan: {ctx.scan_type}\nClinical history: {ctx.history or 'none given'}\nFindings:\n{ctx.findings}"
    if history:
        s += "\n\nEARLIER QUESTIONS:\n" + "\n".join(f"Q: {h.question}\nA: {h.answer}" for h in history[-3:])
    return s


async def _text(system: str, user: str, model: str = QWEN) -> str:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=model, output_type=str, system_prompt=system, user_prompt=user, api_key="",
        model_settings={"temperature": 0.2, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return str(r.output).strip()


async def _route(question: str, ctx: Context, history: list[QA]) -> RawRoute:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawRoute, system_prompt=ROUTE_SYS,
        user_prompt=f"{_ctx(ctx, history)}\n\nQUESTION: {question}", api_key="",
        model_settings={"temperature": 0, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def _grounded(question: str, material: str, ctx: Context, history: list[QA]) -> str:
    return await _text(GROUNDED_SYS, f"MATERIAL:\n{material[:16000]}\n\n{_ctx(ctx, history)}\n\nQUESTION: {question}")


async def _search_phrase(question: str, name: str, version: str) -> str:
    return (await _text(PHRASE_SYS, f"GUIDELINE: {name} {version}\nQUESTION: {question}")).splitlines()[0][:120]


async def _general_answer(question: str, ctx: Context, history: list[QA]) -> str:
    return await _text(GENERAL_SYS, f"{_ctx(ctx, history)}\n\nQUESTION: {question}")


def _material(db: Session, key: str) -> str:
    from . import tnm
    if tnm.is_tnm(key):
        site = tnm.site_for(key)
        return tnm.material(site) if site else ""
    row = R.by_key(db, key)
    if row is None:
        return ""
    e = R.entry(row)
    parts = [e.content.summary]
    for b in e.content.checked():
        parts.append(f"{b.name}: {b.rule}\n" + "\n".join(f"- {o.when}: {o.classification} {o.recommendation}" for o in b.outputs))
    parts += [f"Q: {s.question}\nA: {s.answer}" for s in e.content.supplements]
    parts += [c.text for c in R.chunks(row)]
    return "\n\n".join(p for p in parts if p)


async def _in_card(db: Session, question: str, key: str, ctx: Context, history: list[QA]) -> AskResult:
    from . import tnm
    if tnm.is_tnm(key):   # offline staging data: grounded in it, never a gap search
        site = tnm.site_for(key)
        material = tnm.material(site) if site else ""
        return AskResult(kind="card", key=key, entry=tnm.entry(site) if site else None,
                         answer=await _grounded(question, material, ctx, history))
    row = R.by_key(db, key)
    if row is None:
        return AskResult(kind="card", key=key, answer="", supported=False, error="unknown guideline")
    e = R.entry(row)
    material = _material(db, key)
    if material and await J.answers(material, question) >= J.ANSWERS_MIN:
        return AskResult(kind="card", key=key, entry=e, answer=await _grounded(question, material, ctx, history))
    phrase = _safe_phrase(await _search_phrase(question, e.name, e.version), e.name, e.version)
    chunks, sources = await S.gather([phrase], branch="")
    new = "\n\n".join(c.text for c in chunks)
    if new and await J.answers(new, question) >= J.ANSWERS_MIN:
        answer = await _grounded(question, new, ctx, history)
        R.upsert(db, key=key, name=e.name, version=e.version, aliases=[], publication=None,
                 content=GuidelineContent(supplements=[Supplement(question=question, answer=answer,
                                                                  quote=chunks[0].text[:300], url=chunks[0].url)]),
                 sources=sources, chunks=chunks)
        return AskResult(kind="card", key=key, entry=R.entry(R.by_key(db, key)), answer=answer, searched=True)
    general = await _general_answer(question, ctx, history)
    return AskResult(kind="card", key=key, entry=e, answer=f"{NOT_IN_GUIDELINE} {general}", searched=True,
                     supported=False)


async def ask(db: Session, question: str, key: str | None, ctx: Context, history: list[QA],
              finding_id: str = "") -> AskResult:
    """Never raises: a failure returns an error the panel shows with a retry."""
    try:
        if key:
            return await _in_card(db, question, key, ctx, history)
        raw = await _route(question, ctx, history)
        if not raw.guideline.strip():
            return AskResult(kind="general", answer=raw.answer.strip())
        from .matcher import RawSystem, Finding, _card
        card = await _card(db, Finding(id=finding_id or "q", text=question), RawSystem(name=raw.guideline, version=raw.version))
        entry = await resolve_guideline(db, card) if card else None
        if card is None or entry is None:
            return AskResult(kind="general", answer=await _general_answer(question, ctx, history), supported=False)
        res = await _in_card(db, question, entry.key, ctx, history)
        card = card.model_copy(update={"key": entry.key, "known": True, "status": entry.status})
        return res.model_copy(update={"card": card})
    except Exception as ex:
        logger.warning("[copilot.ask] %s: %s", type(ex).__name__, str(ex)[:200])
        return AskResult(kind="card" if key else "general", key=key, answer="", supported=False,
                         error=f"{type(ex).__name__}")
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_ask.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/ask.py backend/tests/test_copilot_ask.py
git commit -m "feat(copilot): ask with Jev gap gate, targeted gap search and supplements"
```

---

### Task 9: Recommendation suggestions

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/recs.py`
- Test: `backend/tests/test_copilot_recs.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_recs.py
from rapid_reports_ai.hybrid_stack.copilot import recs as Rc


async def test_suggestions_capped_and_deduped_against_applied(monkeypatch):
    async def call(prompt):
        assert "APPLIED" in prompt
        return Rc.RawRecs(items=["Refer to the urology MDT.", "CT chest at 6-12 months.", "a", "b", "c", "d"])
    monkeypatch.setattr(Rc, "_call", call)
    out = await Rc.suggest("CT", "", "findings", "conclusion", ["CT chest at 6-12 months"])
    assert out.items[0] == "Refer to the urology MDT." and "CT chest at 6-12 months." not in out.items
    assert len(out.items) <= Rc.MAX_ITEMS


async def test_failure_returns_empty(monkeypatch):
    async def call(prompt):
        raise RuntimeError("x")
    monkeypatch.setattr(Rc, "_call", call)
    out = await Rc.suggest("CT", "", "f", "", [])
    assert out.items == [] and out.error
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_recs.py -v`
Expected: FAIL.

- [ ] **Step 3: Write the recommendations module**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/recs.py
"""General recommendation suggestions (spec §4.4, §5.6): offered unticked; only ticked items reach the report.
Surveillance intervals and thresholds come only from applied guidelines, never from here."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from ...enhancement_utils import _run_agent_with_model
from ...report_reconcile import QWEN

logger = logging.getLogger(__name__)

MAX_ITEMS = 4
TIMEOUT_S = 10.0

RECS_SYS = """You suggest follow-up actions a radiologist may choose to add as recommendations at the end of a report. They tick the ones they want; the rest are dropped.
- 0-4 items, most important first; each one short sentence in British English.
- Only actions the findings or the clinical question call for: referral to a named specialty or multidisciplinary meeting, further imaging with a named modality, correlation with prior imaging or a named test.
- Never an item already APPLIED, never a surveillance interval, size threshold or classification (those come only from guidelines the radiologist applies), never "clinical correlation" on its own.
- Return an empty list when nothing is called for."""


class RawRecs(BaseModel):
    items: list[str] = Field(default_factory=list)


class RecsResult(BaseModel):
    items: list[str] = Field(default_factory=list)
    ms: int = 0
    error: str | None = None


async def _call(prompt: str) -> RawRecs:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawRecs, system_prompt=RECS_SYS, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


def _n(s: str) -> str:
    return " ".join(s.lower().strip().rstrip(".").split())


async def suggest(scan_type: str, history: str, findings: str, conclusion: str, applied: list[str]) -> RecsResult:
    t0 = time.perf_counter()
    prompt = (f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}\n\n"
              f"CONCLUSION:\n{conclusion or '(none yet)'}\n\nAPPLIED:\n" + ("\n".join(f"- {a}" for a in applied) or "(none)"))
    try:
        raw = await _call(prompt)
    except Exception as e:
        logger.warning("[copilot.recs] %s: %s", type(e).__name__, str(e)[:200])
        return RecsResult(ms=int((time.perf_counter() - t0) * 1000), error=type(e).__name__)
    seen = {_n(a) for a in applied}
    items = []
    for it in raw.items:
        if it.strip() and _n(it) not in seen:
            seen.add(_n(it))
            items.append(it.strip())
    return RecsResult(items=items[:MAX_ITEMS], ms=int((time.perf_counter() - t0) * 1000))
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_recs.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/recs.py backend/tests/test_copilot_recs.py
git commit -m "feat(copilot): general recommendation suggestions"
```

---

### Task 10: Routes, kill switch, status flag, log field, reviewer routes

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py`
- Modify: `backend/src/rapid_reports_ai/main.py`. Import and include the router next to
  `app.include_router(hybrid_stack_router)`, and add the `stack_copilot` flag to the status dict near
  `"hybrid_stack": stack_allowed(),`.
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/routes.py`. Add `copilot: dict | None = None` to `LogRequest`, and
  skip it in the `/log` loop when it is `None`, as `gate` is skipped.
- Test: `backend/tests/test_copilot_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_copilot_routes.py
import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import DictationStackLog, User
from rapid_reports_ai.hybrid_stack.copilot import registry as Reg
from rapid_reports_ai.hybrid_stack.copilot import routes as CR
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Card, GuidelineContent, Preview
from rapid_reports_ai.main import app


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T", is_active=True,
             is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user, monkeypatch):
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    monkeypatch.delenv("RR_STACK_COPILOT", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_kill_switch(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK_COPILOT", "0")
    assert authed.post("/api/canvas/stack/guidelines/match", json={"findings": []}).status_code == 404
    assert CR.copilot_allowed() is False


def test_match_route(authed, monkeypatch):
    async def fake(db, scan_type, history, findings):
        return [Card(key="k@1", name="K", version="1", finding_id=findings[0].id, branch="B")]
    monkeypatch.setattr(CR, "match", fake)
    d = authed.post("/api/canvas/stack/guidelines/match",
                    json={"scan_type": "CT", "findings": [{"id": "u1", "text": "x"}]}).json()
    assert d["cards"][0]["key"] == "k@1" and d["cards"][0]["finding_id"] == "u1"


def test_open_route_returns_entry_and_preview(authed, db_session, monkeypatch):
    Reg.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None,
               content=GuidelineContent(branches=[Branch(name="B", state="checked")]), sources=[], chunks=[])

    async def resolve(db, card):
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def prev(entry, branch, findings, history, answered):
        return Preview(missing=["risk"])
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "preview", prev)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1", "branch": "B"},
        "findings": "x", "clinical_history": ""}).json()
    assert d["entry"]["key"] == "k@1" and d["preview"]["missing"] == ["risk"] and d["error"] is None


def test_open_route_fetch_failure(authed, monkeypatch):
    async def resolve(db, card):
        return None
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "finding_id": "u1"}, "findings": "x"}).json()
    assert d["entry"] is None and d["error"] == "unavailable"


def test_registry_review_routes_need_reviewer(authed, db_session, monkeypatch):
    monkeypatch.setenv("RR_STACK_REVIEWERS", "someone@else")
    assert authed.get("/api/canvas/stack/guidelines/registry").status_code == 403
    monkeypatch.setenv("RR_STACK_REVIEWERS", "rad@nhs.net")
    Reg.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None,
               content=GuidelineContent(), sources=[], chunks=[])
    assert authed.get("/api/canvas/stack/guidelines/registry").json()[0]["key"] == "k@1"
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"status": "verified"}).json() == {"ok": True}
    row = Reg.by_key(db_session, "k@1")
    db_session.refresh(row)
    assert row.status == "verified" and row.verified_by == "rad@nhs.net"
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"status": "discarded"}).json() == {"ok": True}
    assert Reg.by_key(db_session, "k@1") is None


def test_log_accepts_copilot(authed, db_session):
    authed.post("/api/canvas/stack/log", json={"session_id": "s1", "copilot": {"applied": ["k@1"]}})
    assert db_session.query(DictationStackLog).filter_by(session_id="s1").first().copilot == {"applied": ["k@1"]}
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_routes.py -v`
Expected: FAIL (an import error).

- [ ] **Step 3: Write the routes**

```python
# backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py
"""Copilot endpoints (spec §5). On with the hybrid stack unless RR_STACK_COPILOT=0 (kill switch). Reviewers
(RR_STACK_REVIEWERS) verify, edit or discard registry entries."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Literal, Mapping

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...database.models import GuidelineRegistry, User
from ..routes import _reviewer, stack_allowed
from . import registry as Reg
from .ask import QA, AskResult, Context, ask
from .fetch import resolve_guideline
from .matcher import Finding, match
from .preview import preview
from .recs import RecsResult, suggest
from .types import Card, Entry, GuidelineContent, Preview

router = APIRouter(prefix="/api/canvas/stack/guidelines", tags=["stack-copilot"])


def copilot_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_STACK_COPILOT", "1") != "0" and stack_allowed(env)


def _require() -> None:
    if not copilot_allowed():
        raise HTTPException(status_code=404, detail="Not Found")


class MatchRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: list[Finding] = Field(default_factory=list)


class MatchResult(BaseModel):
    cards: list[Card] = Field(default_factory=list)
    ms: int = 0


class OpenRequest(BaseModel):
    card: Card
    findings: str = ""
    clinical_history: str = ""
    answered: dict[str, str] = Field(default_factory=dict)


class OpenResult(BaseModel):
    entry: Entry | None = None
    preview: Preview | None = None
    ms: int = 0
    error: str | None = None


class AskRequest(BaseModel):
    question: str
    key: str | None = None
    finding_id: str = ""
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""
    history: list[QA] = Field(default_factory=list)


class RecsRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""
    conclusion: str = ""
    applied: list[str] = Field(default_factory=list)


class RegistryUpdate(BaseModel):
    status: Literal["verified", "draft", "discarded"] | None = None
    content: GuidelineContent | None = None


@router.post("/match", response_model=MatchResult)
async def copilot_match(req: MatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    t0 = time.perf_counter()
    cards = await match(db, req.scan_type[:300], req.clinical_history[:2000], req.findings[:20])
    return MatchResult(cards=cards, ms=int((time.perf_counter() - t0) * 1000))


@router.post("/open", response_model=OpenResult)
async def copilot_open(req: OpenRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Resolve the card's guideline (registry or targeted fetch), then preview it for this case."""
    _require()
    t0 = time.perf_counter()
    entry = await resolve_guideline(db, req.card)
    if entry is None:
        return OpenResult(ms=int((time.perf_counter() - t0) * 1000), error="unavailable")
    branch = req.card.branch or next((b.name for b in entry.content.checked()), "")
    prev = await preview(entry, branch, req.findings[:6000], req.clinical_history[:2000], req.answered)
    return OpenResult(entry=entry, preview=prev, ms=int((time.perf_counter() - t0) * 1000))


@router.post("/preview", response_model=OpenResult)
async def copilot_preview(req: OpenRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The preview alone (an input answered): registry only, never a fetch."""
    _require()
    t0 = time.perf_counter()
    row = Reg.by_key(db, req.card.key)
    if row is None:
        return OpenResult(error="unknown guideline")
    entry = Reg.entry(row)
    prev = await preview(entry, req.card.branch, req.findings[:6000], req.clinical_history[:2000], req.answered)
    return OpenResult(entry=entry, preview=prev, ms=int((time.perf_counter() - t0) * 1000))


@router.post("/ask", response_model=AskResult)
async def copilot_ask(req: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    ctx = Context(scan_type=req.scan_type[:300], history=req.clinical_history[:2000], findings=req.findings[:6000])
    return await ask(db, req.question[:1000], req.key, ctx, req.history[-3:], req.finding_id)


@router.post("/recommendations", response_model=RecsResult)
async def copilot_recs(req: RecsRequest, user: User = Depends(get_current_user)):
    _require()
    return await suggest(req.scan_type[:300], req.clinical_history[:2000], req.findings[:6000], req.conclusion[:2000],
                         req.applied[:10])


@router.get("/registry")
async def list_registry(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _reviewer(user)
    rows = db.query(GuidelineRegistry).order_by(GuidelineRegistry.status, GuidelineRegistry.updated_at.desc()).all()
    return [{**Reg.entry(r).model_dump(), "chunks": r.chunks or [],
             "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows]


@router.post("/registry/{key}")
async def update_registry(key: str, upd: RegistryUpdate, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Verify, edit or discard (the next open re-fetches)."""
    _reviewer(user)
    row = Reg.by_key(db, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown guideline")
    if upd.status == "discarded":
        db.delete(row)
        db.commit()
        return {"ok": True}
    if upd.content is not None:
        row.content = upd.content.model_dump()
    if upd.status:
        row.status = upd.status
        if upd.status == "verified":
            row.verified_by = user.email
            row.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"ok": True}
```

In `main.py`, after `app.include_router(hybrid_stack_router)`:

```python
from .hybrid_stack.copilot.routes import router as stack_copilot_router  # noqa: E402
app.include_router(stack_copilot_router)
```

In the status dict, after `"hybrid_stack_shadow_rate": shadow_rate(),`, add:

```python
        # the scratchpad Copilot (guideline cards): on with the stack; RR_STACK_COPILOT=0 turns it off
        "stack_copilot": copilot_allowed(),
```

Add `copilot_allowed` to the local import at the status function:
`from rapid_reports_ai.hybrid_stack.copilot.routes import copilot_allowed`.

In `hybrid_stack/routes.py` `LogRequest`, after `report_id`:

```python
    copilot: dict | None = None   # Copilot session record (spec §5.7)
```

In the `/log` loop, change the skip line to:

```python
        if k == "session_id" or (k in ("gate", "report_id", "copilot") and v is None):
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest tests/test_copilot_routes.py tests/test_hybrid_stack_routes.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py backend/src/rapid_reports_ai/main.py \
  backend/src/rapid_reports_ai/hybrid_stack/routes.py backend/tests/test_copilot_routes.py
git commit -m "feat(copilot): routes, kill switch, status flag, reviewer registry, session log field"
```

---

### Task 11: `stack_fallback` recommendations rule

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_brief.py`, in `stack_fallback` before the
  `if conclusion.strip():` block.
- Test: whichever test file covers `stack_fallback` (`grep -ln "stack_fallback" backend/tests`). Add to it.

- [ ] **Step 1: Write the failing test**

```python
def test_stack_fallback_recommendations_rule():
    from rapid_reports_ai.quick_report_brief import RECS_LINE, stack_fallback
    b = stack_fallback("", "Bosniak IIF cyst.")
    assert "Scratchpad Recommendations" in b.text and RECS_LINE in b.text
    assert RECS_LINE == "Recommendations (selected by the radiologist):"
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && PYTHONPATH=src poetry run pytest <that file> -k recommendations_rule -v`
Expected: FAIL (an `ImportError` on `RECS_LINE`).

- [ ] **Step 3: Add the rule**

At module level, next to `STACK_FALLBACK_DROP`:

```python
# The findings block's last line when the radiologist ticked recommendations (scratchpad copilot §6). The frontend
# writes the same label (regionState.RECS_LINE).
RECS_LINE = "Recommendations (selected by the radiologist):"
```

In `stack_fallback`, before `if conclusion.strip():`:

```python
    secs.append(Section("Scratchpad Recommendations", bullets=[Bullet("Recommendations", [
        f"- **Recommendations:** when the FINDINGS input has a line starting '{RECS_LINE}', write a RECOMMENDATIONS "
        "section after the impression containing exactly those items, each in report style, adding none and dropping "
        "none; never put them in the impression or the findings. With no such line, write no recommendations section."])]))
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && PYTHONPATH=src poetry run pytest <that file> -v`
Expected: all pass. If an existing assertion counts sections, update it.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/quick_report_brief.py backend/tests/<that file>
git commit -m "feat(stack): Recommendations section from the radiologist's ticked items"
```

---

# Phase B: labs (hand read by Claude; no LLM judge; two runs at most)

### Task 12: Seed fetch lab, and seeding the dev registry

**Files:**
- Create: `backend/scripts/copilot_eval/seed_fetch_lab.py`
- Create: `backend/scripts/copilot_eval/fixtures/seed.json`

- [ ] **Step 1: Write the seed list**

```json
[
  {"name": "Fleischner", "version": "2017", "finding": "8 mm solid nodule in the right upper lobe."},
  {"name": "Bosniak", "version": "2019", "finding": "3 cm left renal cyst with one thin enhancing septum."},
  {"name": "ESE adrenal incidentaloma", "version": "2023", "finding": "2 cm left adrenal nodule, 25 HU unenhanced."},
  {"name": "BTA U classification", "version": "2014", "finding": "1.5 cm solid hypoechoic thyroid nodule with microcalcification."},
  {"name": "O-RADS US", "version": "2022", "finding": "4 cm unilocular smooth left ovarian cyst, postmenopausal."},
  {"name": "LI-RADS CT/MRI", "version": "2018", "finding": "2.2 cm arterially enhancing liver observation with washout, cirrhotic liver."},
  {"name": "Kellgren-Lawrence", "version": "", "finding": "Medial knee joint space narrowing with osteophytes."}
]
```

Hassan may edit this list in plan review. TNM is not here: it comes from the offline provider (Task 5b).

- [ ] **Step 2: Write the lab script**

```python
# backend/scripts/copilot_eval/seed_fetch_lab.py
"""Seed fetch lab (plan Task 12, spec §8.2). For each seed: matcher (skeleton + branch) on the seed finding, then the
targeted fetch for the case branch and a synchronous fill of the rest; writes everything a hand read needs, plus the
Jev scores, to OUT (outside the repo). Run against the local dev DB so the drafts land in its registry.

  cd backend && PYTHONPATH=src RR_DICTATION_V2=1 .venv/bin/python scripts/copilot_eval/seed_fetch_lab.py OUT_DIR
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from rapid_reports_ai.database import SessionLocal
from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import jev as J
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R

SEEDS = json.loads((Path(__file__).parent / "fixtures" / "seed.json").read_text())


async def one(seed: dict, out: Path) -> dict:
    F._spawn_fill = lambda *a, **k: None          # the lab fills synchronously below, to time and record it
    rec: dict = {"seed": seed}
    with SessionLocal() as db:
        t0 = time.perf_counter()
        cards = await M.match(db, "CT", "", [M.Finding(id="u1", text=seed["finding"])])
        rec["match_ms"] = int((time.perf_counter() - t0) * 1000)
        rec["cards"] = [c.model_dump() for c in cards]
        card = next((c for c in cards if seed["name"].split()[0].lower() in c.name.lower()), cards[0] if cards else None)
        if card is None:
            rec["error"] = "no card"
            return rec
        t0 = time.perf_counter()
        entry = await F.resolve_guideline(db, card)
        rec["first_pass_ms"] = int((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        await F._fill(card, F.to_fill(card.skeleton, entry.content if entry else F.GuidelineContent()))
        rec["fill_ms"] = int((time.perf_counter() - t0) * 1000)
        db.expire_all()
        row = R.by_key(db, card.key)
        rec["entry"] = R.entry(row).model_dump() if row else None
        rec["chunks"] = row.chunks if row else []
        if row:   # per-branch coverage scores on the final chunks, for the Jev fixture
            text = "\n\n".join(c["text"] for c in row.chunks)
            rec["coverage"] = await J.coverage(text, [b.name for b in R.entry(row).content.branches])
    (out / f"{card.key.replace('@', '_')}_{os.getpid()}.json").write_text(json.dumps(rec, indent=1, default=str))
    return rec


async def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    recs = [await one(s, out) for s in SEEDS]
    for r in recs:
        e = r.get("entry") or {}
        states = {b["name"]: b["state"] for b in (e.get("content") or {}).get("branches", [])}
        print(f"{r['seed']['name']:28} first={r.get('first_pass_ms')}ms fill={r.get('fill_ms')}ms {states}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 3: Run it once against the local dev DB**

First apply the migration locally: `cd backend && PYTHONPATH=src .venv/bin/alembic upgrade head`. In the local dev DB
(`tnm_test`), the stack tables were created outside alembic. If `upgrade` fails on existing tables, run the migration's
`CREATE TABLE` and `ALTER TABLE` by hand, as was done for the earlier stack columns (memory note).

Run: `PYTHONPATH=src RR_DICTATION_V2=1 .venv/bin/python scripts/copilot_eval/seed_fetch_lab.py <scratchpad>/copilot_lab/seed_run1`
Expected: one line per seed, with first-pass and fill timings and the branch states.

- [ ] **Step 4: Hand read (Claude)**

For every seed, open its JSON and check each `checked` branch's outputs against `chunks` and the source URLs. Record
in `<scratchpad>/copilot_lab/seed_hand_read.md`:
- correct and wrong thresholds or intervals;
- branches wrongly `not_available`, and branches wrongly `checked`;
- tier-1/2 vs tier-3 sources;
- first-pass latency.

From the same read, build the Jev fixtures (`fixtures/jev_gates.json`):
- **coverage:** at least 12 covered and 12 missing (branch, chunk text) pairs, taken from the runs;
- **evidence:** at least 12 true exact, 12 true reworded or table-mangled, and 12 wrong-value (claim, chunk text)
  triples. Wrong values come from editing true claims, e.g. a changed interval or a swapped category.
- **answers:** at least 10 questions the material answers and 10 it doesn't, per a few seeds.

- [ ] **Step 5: Set the thresholds**

Write a small loop in the same script under `--gates` that scores the fixtures with `J.coverage`, `J.evidence` and
`J.answers`. Set each `*_MIN` in `copilot/jev.py` at the lowest value with **zero false yes answers** on its fixture,
then round up to the next 0.05. Record recall at that bar in the comment next to each constant, in the house style
(e.g. `# lab 2026-10-1x (24 pairs): covered 11/12, false 0/12`).

- [ ] **Step 6: Second run (only if Step 5 or a fix changed behaviour)**

Re-run Step 3 into `seed_run2`, and re-read only the seeds that changed.

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/copilot_eval backend/src/rapid_reports_ai/hybrid_stack/copilot/jev.py
git commit -m "lab(copilot): seed fetch lab, Jev gate fixtures, thresholds set"
```

Outputs stay in the scratchpad. Summarise the hand read in the commit body: seeds fully checked, wrong values found,
mean first-pass latency.

---

### Task 13: Match, preview and ask lab

**Files:**
- Create: `backend/scripts/copilot_eval/match_preview_ask_lab.py`
- Create: `backend/scripts/copilot_eval/fixtures/cases.json`
- Create: `backend/scripts/copilot_eval/fixtures/questions.json`

- [ ] **Step 1: Build the fixtures from production stack sessions**

Under standing prod-read permission (memory), query `dictation_stack_logs` through the Metabase `/api/dataset`
method (memory: prod smoke testing):
- 20 confirmed sessions with a guideline-bearing abnormal finding;
- 10 confirmed sessions whose abnormal findings carry no guideline. These are the negative controls.

For each, take the scan type, the history and the abnormal sentences only. Write `cases.json` as
`[{id, scan_type, history, findings: [{id, text}], expected: [{key_prefix, branch}] }]`. `expected` is filled by
Claude's own reading. The negative controls have `expected: []`.

Write `questions.json` with 24 questions:
- 8 card-scoped, answerable from a seed;
- 4 card-scoped, not answerable;
- 6 general that imply a seed guideline;
- 6 general with no guideline.

Each is `{q, scope_key|null, expect: "card"|"general", expect_key|null}`.

Keep both files out of git if they contain prod text: put them under the scratchpad and pass the path as an argument.
Only synthetic stand-ins are committed.

Also write `tnm_cases.json`:
- 30 primary-tumour findings across at least 12 sites, with lung, colorectal, kidney, pancreas, oesophagus, breast,
  head and neck, bladder and gynaecological sites well represented;
- 20 negative controls: metastases, benign masses, indeterminate incidental lesions, and a primary that is already
  treated and being followed.

Each item is `{id, finding, expect_site | null}`, taken from prod stack logs where possible, otherwise synthetic.

- [ ] **Step 2: Write the lab script**

```python
# backend/scripts/copilot_eval/match_preview_ask_lab.py
"""Match, preview and ask lab (plan Task 13, spec §8.1, §8.3, §8.4). Writes per-case JSON for a hand read; prints a
summary. Uses the registry the seed lab filled.

  cd backend && PYTHONPATH=src RR_DICTATION_V2=1 .venv/bin/python scripts/copilot_eval/match_preview_ask_lab.py CASES QUESTIONS OUT
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from rapid_reports_ai.database import SessionLocal
from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot import tnm


async def cases(path: Path, out: Path) -> None:
    F._spawn_fill = lambda *a, **k: None
    hits = misses = wrong = 0
    for c in json.loads(path.read_text()):
        with SessionLocal() as db:
            cards = await M.match(db, c["scan_type"], c["history"], [M.Finding(**f) for f in c["findings"]])
            previews = []
            for card in cards:
                row = R.by_key(db, card.key)
                if row is not None:
                    findings = "\n".join(f["text"] for f in c["findings"] if f["id"] == card.finding_id)
                    previews.append({"card": card.id, "preview": (await P.preview(R.entry(row), card.branch, findings, c["history"], {})).model_dump()})
        got = {(cd.key.split("@")[0], cd.branch) for cd in cards}
        exp = {(e["key_prefix"], e["branch"]) for e in c["expected"]}
        hits += len({k for k, _ in exp} & {k for k, _ in got})
        misses += len({k for k, _ in exp} - {k for k, _ in got})
        wrong += len({k for k, _ in got} - {k for k, _ in exp})
        (out / f"case_{c['id']}_{os.getpid()}.json").write_text(json.dumps(
            {"case": c, "cards": [x.model_dump() for x in cards], "previews": previews}, indent=1))
    print(f"match: expected found {hits}, missed {misses}, unexpected cards {wrong}")


async def questions(path: Path, out: Path) -> None:
    ok = 0
    qs = json.loads(path.read_text())
    rows = []
    for q in qs:
        with SessionLocal() as db:
            res = await A.ask(db, q["q"], q["scope_key"], A.Context(scan_type="CT"), [])
        landed = res.kind
        key = res.key or (res.card.key if res.card else None)
        right = landed == q["expect"] and (q["expect_key"] is None or (key or "").startswith(q["expect_key"]))
        ok += right
        rows.append({**q, "kind": landed, "key": key, "answer": res.answer, "searched": res.searched,
                     "supported": res.supported, "right": right})
    (out / f"questions_{os.getpid()}.json").write_text(json.dumps(rows, indent=1))
    print(f"ask routing: {ok}/{len(qs)} landed right")


async def tnm_arms(path: Path, out: Path) -> None:
    """Spec §8.5: (a) closed list + Jev gate (scores recorded for every threshold) vs (b) hybrid_tnm_search (needs a
    Postgres with pgvector and tnm_staging seeded, plus OPENAI_API_KEY)."""
    from rapid_reports_ai.tnm_lookup import hybrid_tnm_search
    rows = []
    for c in json.loads(path.read_text()):
        M.clear_cache()
        with SessionLocal() as db:
            raw = await M._call(M._prompt("CT", "", [M.Finding(id="u1", text=c["finding"])], []))
            site = next((s.site for rf in raw.findings for s in rf.systems if s.name.upper() == "TNM"), "")
            gate = await M._tnm_gate(c["finding"], site) if site in tnm.sites() else None
            try:
                hy = hybrid_tnm_search(c["finding"], db, top_k=1)
                hybrid = hy[0].tumour if hy else None
            except Exception as e:
                hybrid = f"error: {type(e).__name__}"
        rows.append({**c, "a_site": site or None, "a_gate": gate, "b_site": hybrid})
    (out / f"tnm_arms_{os.getpid()}.json").write_text(json.dumps(rows, indent=1))
    for bar in (0.5, 0.6, 0.7, 0.8):
        a_ok = sum((r["a_site"] == r["expect_site"] and (r["a_gate"] or 0) >= bar) or (r["expect_site"] is None and not ((r["a_gate"] or 0) >= bar)) for r in rows)
        a_false = sum(r["expect_site"] is None and (r["a_gate"] or 0) >= bar for r in rows)
        print(f"arm a @ {bar}: right {a_ok}/{len(rows)}, false staging cards {a_false}")
    b_ok = sum(r["b_site"] == r["expect_site"] for r in rows)
    b_false = sum(r["expect_site"] is None and r["b_site"] not in (None,) for r in rows)
    print(f"arm b (hybrid): right {b_ok}/{len(rows)}, false staging cards {b_false}")


async def main(cases_path: str, questions_path: str, out_dir: str, tnm_path: str = "") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    await cases(Path(cases_path), out)
    await questions(Path(questions_path), out)
    if tnm_path:
        await tnm_arms(Path(tnm_path), out)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:5]))
```

- [ ] **Step 3: Run once, then hand read**

Run it with the scratchpad paths. Then read every case file and record in `<scratchpad>/copilot_lab/mpa_hand_read.md`:
- **Match:**
  - expected guideline found;
  - **wrong or irrelevant cards** (the precision target: zero cards on the negative controls is the bar);
  - branch correct;
  - key normalisation.
- **Preview:**
  - settled inputs correct;
  - missing correct;
  - proposal correct;
  - any proposal the numeric guard dropped.
- **Ask:**
  - landing;
  - grounded answers correct;
  - gap answers honest.

- **TNM arms:**
  - Set `TNM_GATE_MIN` in `matcher.py` at the lowest bar with zero false staging cards.
  - Compare arm (a) at that bar with arm (b).
  - **Arm (a) stays on the Copilot path only if it is at least as accurate as (b).** Otherwise, report to Hassan and
    switch `_tnm_card` to take the site from `hybrid_tnm_search` instead. Prod already has pgvector; local may not.
  - If (b) can't run locally, say so and run it against a Postgres with pgvector before deciding. Don't decide on arm
    (a) alone.

- [ ] **Step 4: Fix and re-run (one more run at most)**

Tighten the prompts in `matcher.py`, `preview.py` or `ask.py` for each failure pattern. Keep them case-agnostic. Then
re-run once. If precision on the negative controls is still not zero, stop and report to Hassan before building the
frontend.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/copilot_eval backend/src/rapid_reports_ai/hybrid_stack/copilot
git commit -m "lab(copilot): match/preview/ask lab and prompt fixes"
```

Put the hand-read summary in the commit body.

---

# Phase C: frontend

### Task 14: Mock-up checkpoint (Hassan approves)

- [ ] **Step 1:** Load the `artifact-design` skill. Then publish a single-page clickable mock-up of the scratchpad and
  the Copilot panel, using the house dark theme (`bg-gray-900`, white/5 borders, amber for checklist rows, emerald
  for normals, violet and rose taken). It shows:
  - a matched card, an opened card loading, an opened card with an input, a draft entry's "unverified · sources"
    label, Apply and Applied;
  - a card thread, the General group and the ask input;
  - the enrichment line under a finding;
  - the Recommendations checklist under the conclusion.

  Propose **sky/cyan** as the enrichment tint. It's the only hue family not yet used in the stack view.
- [ ] **Step 2:** Send Hassan the link. **Stop until he approves the tint and layout.** Record the agreed classes at the
  top of `CopilotPanel.svelte` (Task 17) in a comment.

---

### Task 15: Frontend types and API

**Files:**
- Modify: `frontend/src/lib/hybrid-stack/types.ts`
- Modify: `frontend/src/lib/hybrid-stack/api.ts`
- Test: `frontend/src/lib/hybrid-stack/api.test.ts` (additions)

- [ ] **Step 1: Write the failing test** (append to `api.test.ts`)

```ts
import { postAsk, postMatch, postOpen, postRecommendations } from './api';

describe('copilot api', () => {
	it('posts to the guidelines prefix', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ cards: [], ms: 1 })));
		vi.stubGlobal('fetch', fetchMock);
		await postMatch('tok', { scan_type: 'CT', clinical_history: '', findings: [{ id: 'u1', text: 'x' }] });
		const [url] = fetchMock.mock.calls[0] as unknown as [string];
		expect(url.endsWith('/api/canvas/stack/guidelines/match')).toBe(true);
	});
	it('open, ask and recommendations hit their routes', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({})));
		vi.stubGlobal('fetch', fetchMock);
		await postOpen('t', { card: { key: 'k@1', name: 'K', version: '1', finding_id: 'u1', why: '', branch: '', skeleton: [], known: false, status: 'new' }, findings: 'x', clinical_history: '', answered: {} });
		await postAsk('t', { question: 'q', key: null, finding_id: '', scan_type: '', clinical_history: '', findings: '', history: [] });
		await postRecommendations('t', { scan_type: '', clinical_history: '', findings: '', conclusion: '', applied: [] });
		const urls = fetchMock.mock.calls.map((c) => (c as unknown as [string])[0]);
		expect(urls.map((u) => u.split('/guidelines/')[1])).toEqual(['open', 'ask', 'recommendations']);
	});
});
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/api.test.ts`
Expected: FAIL, because the imports don't exist yet.

- [ ] **Step 3: Add the types** (append to `types.ts`)

```ts
// ── Scratchpad Copilot (spec 2026-10-12-scratchpad-copilot) ──────────────────────────────────────────────────────
export interface CopilotPublication { title: string; body: string; year: string }
export interface CopilotCard {
	key: string; name: string; version: string; finding_id: string; why: string; branch: string; skeleton: string[];
	publication?: CopilotPublication; known: boolean; status: 'draft' | 'verified' | 'new';
	from_question?: boolean; // added by an ask, not the matcher
}
export interface GuidelineInput { id: string; question: string; options: string[]; settled_by?: string }
export interface GuidelineOutput { when: string; classification: string; recommendation: string; quote: string }
export interface GuidelineBranch { name: string; state: 'checked' | 'not_available' | 'pending'; inputs: GuidelineInput[]; rule: string; outputs: GuidelineOutput[] }
export interface GuidelineEntry {
	key: string; name: string; version: string; status: 'draft' | 'verified';
	content: { applies_to: string; summary: string; branches: GuidelineBranch[]; supplements: { question: string; answer: string; url: string }[] };
	sources: { url: string; title: string; tier: number }[];
}
export interface CopilotProposal { classification: string; line: string; recommendation: string }
export interface CopilotPreview { settled: { input: string; value: string; quote: string }[]; missing: string[]; proposal: CopilotProposal | null }
export interface OpenResult { entry: GuidelineEntry | null; preview: CopilotPreview | null; ms: number; error: string | null }
export interface AskResult {
	kind: 'card' | 'general'; answer: string; key: string | null; card: CopilotCard | null; entry: GuidelineEntry | null;
	searched: boolean; supported: boolean; error: string | null;
}
export interface RecsResult { items: string[]; ms: number; error: string | null }
export interface QA { question: string; answer: string; supported?: boolean; error?: boolean }
/** A guideline the radiologist applied: a line under its finding and (when it has one) a ticked recommendation. */
export interface Enrichment { key: string; version: string; status: 'draft' | 'verified'; finding_id: string; region: string; line: string; recommendation: string }
export interface RecItem { text: string; source: 'guideline' | 'suggested' | 'typed'; key?: string; ticked: boolean }
```

Add to `GateRecord`, after `checks?`:

```ts
	enrichments?: Enrichment[]; // guidelines applied in the Copilot (spec §6)
	recommendations?: RecItem[]; // every item offered and whether it was ticked; only ticked ones reach the report
```

- [ ] **Step 4: Add the API helpers** (append to `api.ts`; extend the type import)

```ts
async function postCopilot<T>(token: string | null, path: string, body: unknown): Promise<T> {
	return post<T>(token, `guidelines/${path}`, body);
}
export const postMatch = (token: string | null, body: { scan_type: string; clinical_history: string; findings: { id: string; text: string }[] }) =>
	postCopilot<{ cards: CopilotCard[]; ms: number }>(token, 'match', body);
export const postOpen = (token: string | null, body: { card: CopilotCard; findings: string; clinical_history: string; answered: Record<string, string> }) =>
	postCopilot<OpenResult>(token, 'open', body);
export const postPreview = (token: string | null, body: { card: CopilotCard; findings: string; clinical_history: string; answered: Record<string, string> }) =>
	postCopilot<OpenResult>(token, 'preview', body);
export const postAsk = (token: string | null, body: { question: string; key: string | null; finding_id: string; scan_type: string; clinical_history: string; findings: string; history: QA[] }) =>
	postCopilot<AskResult>(token, 'ask', body);
export const postRecommendations = (token: string | null, body: { scan_type: string; clinical_history: string; findings: string; conclusion: string; applied: string[] }) =>
	postCopilot<RecsResult>(token, 'recommendations', body);
```

Extend the `./types` import line with
`AskResult, CopilotCard, OpenResult, QA, RecsResult`. The `post` helper already prefixes `/api/canvas/stack/`.

- [ ] **Step 5: Run the tests and the type check**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/api.test.ts && npm run check`
Expected: the tests pass, and check reports no new errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/hybrid-stack/types.ts frontend/src/lib/hybrid-stack/api.ts frontend/src/lib/hybrid-stack/api.test.ts
git commit -m "feat(copilot): frontend types and API helpers"
```

---

### Task 16: Pure Copilot state, and the findings block

**Files:**
- Create: `frontend/src/lib/hybrid-stack/copilot.ts`
- Create: `frontend/src/lib/hybrid-stack/copilot.test.ts`
- Modify: `frontend/src/lib/hybrid-stack/regionState.ts` (`buildFindingsBlock`, export `APPLIED`, `RECS_LINE`)
- Test: `frontend/src/lib/hybrid-stack/regionState.test.ts` (additions)

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/hybrid-stack/copilot.test.ts
import { describe, expect, it } from 'vitest';
import { abnormalFindings, cardId, enrichmentExtra, enrichmentLines, fileAnswer, mergeRecs, pruneEnrichments, recsLine, upsertEnrichment } from './copilot';
import type { CopilotCard, Enrichment, StackUnit } from './types';

const u = (id: number, text: string, group: string, abnormal = true): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal, pinned: false, heading: false
});
const card = (key: string, finding_id = 'u1', extra: Partial<CopilotCard> = {}): CopilotCard => ({
	key, name: key.split('@')[0], version: '1', finding_id, why: '', branch: 'B', skeleton: [], known: true, status: 'draft', ...extra
});
const enr = (key: string, finding_id = 'u1', region = 'Lungs'): Enrichment => ({
	key, version: '1', status: 'draft', finding_id, region, line: `${key} line.`, recommendation: `${key} rec.`
});

describe('copilot state', () => {
	it('abnormal findings carry stable ids and regions', () => {
		expect(abnormalFindings([u(1, 'Nodule.', 'Lungs'), u(2, 'Normal liver.', 'Liver', false)])).toEqual([{ id: 'u1', text: 'Nodule.', region: 'Lungs' }]);
	});
	it('files an answer under the scoped card, a resolved card, or General', () => {
		let s = { cards: [card('k@1')], threads: {} as Record<string, { question: string; answer: string }[]>, general: [] as { question: string; answer: string }[] };
		s = fileAnswer(s, 'k@1|u1', { kind: 'card', key: 'k@1', card: null, answer: 'a1' } as never, 'q1');
		expect(s.threads['k@1|u1']).toEqual([{ question: 'q1', answer: 'a1', supported: undefined, error: false }]);
		s = fileAnswer(s, null, { kind: 'card', key: 'n@2', card: card('n@2'), answer: 'a2' } as never, 'q2');
		expect(s.cards.map((c) => c.key)).toEqual(['k@1', 'n@2']);
		expect(s.cards[1].from_question).toBe(true);
		expect(s.threads[cardId(s.cards[1])][0].answer).toBe('a2');
		s = fileAnswer(s, null, { kind: 'card', key: 'k@1', card: card('k@1'), answer: 'a3' } as never, 'q3');
		expect(s.cards.length).toBe(2); // an existing card is reused
		expect(s.threads['k@1|u1'].length).toBe(2);
		s = fileAnswer(s, null, { kind: 'general', key: null, card: null, answer: 'g' } as never, 'q4');
		expect(s.general).toEqual([{ question: 'q4', answer: 'g', supported: undefined, error: false }]);
	});
	it('one enrichment per card; pruned with its finding', () => {
		let e = upsertEnrichment([], enr('k@1'));
		e = upsertEnrichment(e, { ...enr('k@1'), line: 'new.' });
		expect(e.map((x) => x.line)).toEqual(['new.']);
		expect(pruneEnrichments(e, [{ id: 'u2', text: 'x', region: 'Lungs' }])).toEqual([]);
	});
	it('recommendations: applied ticked, suggested unticked, ticks survive, typed kept', () => {
		const prev = [
			{ text: 'Refer to MDT.', source: 'suggested' as const, ticked: true },
			{ text: 'Old suggestion.', source: 'suggested' as const, ticked: false },
			{ text: 'My own.', source: 'typed' as const, ticked: true }
		];
		const out = mergeRecs(prev, [enr('k@1')], ['Refer to MDT.', 'New idea.']);
		expect(out).toEqual([
			{ text: 'k@1 rec.', source: 'guideline', key: 'k@1', ticked: true },
			{ text: 'Refer to MDT.', source: 'suggested', ticked: true },
			{ text: 'New idea.', source: 'suggested', ticked: false },
			{ text: 'My own.', source: 'typed', ticked: true }
		]);
	});
	it('a guideline item unticked by the radiologist stays unticked', () => {
		const prev = [{ text: 'k@1 rec.', source: 'guideline' as const, key: 'k@1', ticked: false }];
		expect(mergeRecs(prev, [enr('k@1')], [])[0].ticked).toBe(false);
	});
	it('findings lines and the recommendations line', () => {
		expect(enrichmentExtra([enr('k@1')]).get('Lungs')).toEqual(['Guideline classification (applied by the radiologist): k@1 line.']);
		expect(enrichmentLines([enr('k@1')])).toEqual(['k@1 line.']);
		expect(recsLine([{ text: 'A.', source: 'typed', ticked: true }, { text: 'B.', source: 'suggested', ticked: false }])).toBe('Recommendations (selected by the radiologist): A.');
		expect(recsLine([])).toBe('');
	});
});
```

Append to `regionState.test.ts`:

```ts
it('the findings block carries applied guidelines under their region and the ticked recommendations', () => {
	const units = [{ id: 1, text: 'An 8 mm nodule.', group: 'Lungs', structure: null, attach_to: null, parts: null, covers: ['Lungs'], abnormal: true, pinned: false, heading: false }];
	const gate = { confirmed_at: '', conclusion_text: 'Nodule.', conclusion_source: 'draft', assumed_normal: [], remainder_normal: [], dictated_normal: [],
		items: [], assumed: {}, removed: [], capped: [], units_hash: '',
		enrichments: [{ key: 'f@2017', version: '2017', status: 'draft', finding_id: 'u1', region: 'Lungs', line: 'Fleischner 2017: high risk.', recommendation: 'CT at 6-12 months.' }],
		recommendations: [{ text: 'CT at 6-12 months.', source: 'guideline', key: 'f@2017', ticked: true }, { text: 'Refer.', source: 'suggested', ticked: false }] } as never;
	const block = buildFindingsBlock(units as never, ['Lungs', 'Conclusion'], gate);
	expect(block).toContain('Guideline classification (applied by the radiologist): Fleischner 2017: high risk.');
	expect(block).toContain('Recommendations (selected by the radiologist): CT at 6-12 months.');
	expect(block).not.toContain('Refer.');
});
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/copilot.test.ts src/lib/hybrid-stack/regionState.test.ts`
Expected: FAIL.

- [ ] **Step 3: Write `copilot.ts`**

```ts
// frontend/src/lib/hybrid-stack/copilot.ts
// Scratchpad Copilot state (spec 2026-10-12-scratchpad-copilot §4): pure functions, so the panel and the scratchpad
// share one set of rules. Cards are discovery only; an enrichment exists only after an explicit Apply; recommendations
// from applied guidelines start ticked, suggestions unticked, and a radiologist's tick survives a redraw.
import { effectiveItems } from './regionState';
import type { AskResult, CopilotCard, Enrichment, QA, RecItem, StackUnit } from './types';

export const APPLIED = 'Guideline classification (applied by the radiologist):';
export const RECS_LINE = 'Recommendations (selected by the radiologist):'; // the backend's quick_report_brief.RECS_LINE

export interface Finding { id: string; text: string; region: string }
export interface Threads { cards: CopilotCard[]; threads: Record<string, QA[]>; general: QA[] }

export const cardId = (c: { key: string; finding_id: string }) => `${c.key}|${c.finding_id}`;

/** The abnormal findings the matcher reads, with ids stable across edits of other lines. */
export function abnormalFindings(units: StackUnit[]): Finding[] {
	return effectiveItems(units)
		.filter((i) => i.abnormal && i.group)
		.map((i) => ({ id: i.part === null ? `u${i.unitId}` : `u${i.unitId}.${i.part}`, text: i.text, region: i.group as string }));
}

/** Where an answer lands (spec §4.3): the scoped card's thread; a resolved card's thread (reused if listed, otherwise
 *  added "from your question"); or General. */
export function fileAnswer(s: Threads, scope: string | null, res: AskResult, question: string): Threads {
	const qa: QA = { question, answer: res.answer, supported: res.supported, error: !!res.error };
	if (scope) return { ...s, threads: { ...s.threads, [scope]: [...(s.threads[scope] ?? []), qa] } };
	if (res.kind === 'card' && res.card) {
		const existing = s.cards.find((c) => c.key === res.card!.key);
		const target = existing ?? { ...res.card, from_question: true };
		const id = cardId(target);
		return { cards: existing ? s.cards : [...s.cards, target], threads: { ...s.threads, [id]: [...(s.threads[id] ?? []), qa] }, general: s.general };
	}
	return { ...s, general: [...s.general, qa] };
}

export function upsertEnrichment(list: Enrichment[], e: Enrichment): Enrichment[] {
	return [...list.filter((x) => cardId(x) !== cardId(e)), e];
}

/** An enrichment goes with its finding (spec §4.1); nothing else removes it but × or Undo. */
export function pruneEnrichments(list: Enrichment[], findings: Finding[]): Enrichment[] {
	const ids = new Set(findings.map((f) => f.id));
	return list.filter((e) => ids.has(e.finding_id));
}

const n = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

export function mergeRecs(prev: RecItem[], enrichments: Enrichment[], suggested: string[]): RecItem[] {
	const was = new Map(prev.map((r) => [n(r.text), r]));
	const guideline: RecItem[] = enrichments.filter((e) => e.recommendation.trim())
		.map((e) => ({ text: e.recommendation, source: 'guideline', key: e.key, ticked: was.get(n(e.recommendation))?.ticked ?? true }));
	const taken = new Set(guideline.map((g) => n(g.text)));
	const sugg: RecItem[] = [];
	for (const t of suggested) {
		if (taken.has(n(t))) continue;
		taken.add(n(t));
		sugg.push({ text: t, source: 'suggested', ticked: was.get(n(t))?.ticked ?? false });
	}
	const typed = prev.filter((r) => r.source === 'typed' && !taken.has(n(r.text)));
	return [...guideline, ...sugg, ...typed];
}

export function enrichmentExtra(list: Enrichment[]): Map<string, string[]> {
	const m = new Map<string, string[]>();
	for (const e of list) m.set(e.region, [...(m.get(e.region) ?? []), `${APPLIED} ${e.line}`]);
	return m;
}

export const enrichmentLines = (list: Enrichment[]) => list.map((e) => e.line);

export function recsLine(recs: RecItem[]): string {
	const ticked = recs.filter((r) => r.ticked).map((r) => r.text.trim()).filter(Boolean);
	return ticked.length ? `${RECS_LINE} ${ticked.join(' ')}` : '';
}
```

- [ ] **Step 4: Change `buildFindingsBlock`** in `regionState.ts`

Import `enrichmentExtra` and `recsLine` from `./copilot`. `copilot.ts` imports `effectiveItems` from `regionState`.
That's a circular import, but it is safe here because both are function declarations used at call time. If the
bundler warns, move `effectiveItems` into a new `items-core.ts`.

Then, in `buildFindingsBlock`, after `const add = …`:

```ts
	for (const [r, lines] of enrichmentExtra(gate.enrichments ?? [])) for (const l of lines) add(r, l);
```

Just before the `DO NOT ASSERT` push:

```ts
	const recs = recsLine(gate.recommendations ?? []);
	if (recs) parts.push(recs);
```

- [ ] **Step 5: Run the tests and check they pass**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/copilot.test.ts src/lib/hybrid-stack/regionState.test.ts`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/hybrid-stack/copilot.ts frontend/src/lib/hybrid-stack/copilot.test.ts \
  frontend/src/lib/hybrid-stack/regionState.ts frontend/src/lib/hybrid-stack/regionState.test.ts
git commit -m "feat(copilot): pure copilot state; findings block carries applied guidelines and ticked recommendations"
```

---

### Task 17: `CopilotPanel.svelte`

**Files:**
- Create: `frontend/src/lib/hybrid-stack/CopilotPanel.svelte`
- Create: `frontend/src/lib/hybrid-stack/CopilotPanel.svelte.test.ts`

The panel is presentational. All calls happen in the scratchpad (Task 19), which passes state and callbacks in.
The panel's per-card state type:

```ts
export type CardView = { open: boolean; loading: boolean; error: string | null; entry: GuidelineEntry | null;
	preview: CopilotPreview | null; answered: Record<string, string>; applied: boolean; previewing: boolean };
```

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/hybrid-stack/CopilotPanel.svelte.test.ts
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import CopilotPanel from './CopilotPanel.svelte';
import type { CopilotCard, GuidelineEntry } from './types';

const card = (key: string, extra: Partial<CopilotCard> = {}): CopilotCard => ({
	key, name: 'Fleischner', version: '2017', finding_id: 'u1', why: 'solid nodule', branch: 'Solid', skeleton: ['Solid'], known: true, status: 'draft', ...extra
});
const entry: GuidelineEntry = {
	key: 'f@2017', name: 'Fleischner', version: '2017', status: 'draft',
	content: { applies_to: '', summary: 'Incidental nodules.', supplements: [], branches: [{ name: 'Solid', state: 'checked', rule: '', outputs: [],
		inputs: [{ id: 'risk', question: 'Patient risk', options: ['Low risk', 'High risk'] }] }] },
	sources: [{ url: 'https://pubs.rsna.org/x', title: 'Fleischner 2017', tier: 1 }]
};
const closed = { open: false, loading: false, error: null, entry: null, preview: null, answered: {}, applied: false, previewing: false };
const base = (extra = {}) => ({
	cards: [card('f@2017')], findings: [{ id: 'u1', text: '7 mm solid nodule.', region: 'Lungs' }], views: { 'f@2017|u1': closed },
	threads: {}, general: [], asking: false, onOpen: vi.fn(), onClose: vi.fn(), onInput: vi.fn(), onApply: vi.fn(), onUndo: vi.fn(), onAsk: vi.fn(), onRetry: vi.fn(), ...extra
});

describe('CopilotPanel', () => {
	it('a matched card shows name, finding and why; clicking opens it', async () => {
		const p = base();
		render(CopilotPanel, p);
		await expect.element(page.getByText('Fleischner 2017', { exact: true })).toBeInTheDocument();
		await expect.element(page.getByText('solid nodule', { exact: true })).toBeInTheDocument();
		await page.getByRole('button', { name: /Fleischner 2017/ }).click();
		expect(p.onOpen).toHaveBeenCalledWith('f@2017|u1');
	});

	it('loading, then inputs with Apply disabled until a proposal exists', async () => {
		const p = base({ views: { 'f@2017|u1': { ...closed, open: true, entry, preview: { settled: [], missing: ['risk'], proposal: null } } } });
		render(CopilotPanel, p);
		await expect.element(page.getByText('Patient risk')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Apply' })).toBeDisabled();
		await expect.element(page.getByText(/unverified/)).toBeInTheDocument();
		await page.getByRole('button', { name: 'High risk' }).click();
		expect(p.onInput).toHaveBeenCalledWith('f@2017|u1', 'risk', 'High risk');
	});

	it('a proposal enables Apply; applied shows Undo', async () => {
		const prev = { settled: [{ input: 'risk', value: 'High risk', quote: '' }], missing: [], proposal: { classification: 'Fleischner 2017 · high risk', line: 'l', recommendation: 'CT at 6-12 months' } };
		const p = base({ views: { 'f@2017|u1': { ...closed, open: true, entry, preview: prev } } });
		const r = render(CopilotPanel, p);
		await expect.element(page.getByText('CT at 6-12 months')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Apply' }).click();
		expect(p.onApply).toHaveBeenCalledWith('f@2017|u1');
		r.rerender({ ...p, views: { 'f@2017|u1': { ...closed, open: true, entry, preview: prev, applied: true } } });
		await page.getByRole('button', { name: 'Undo' }).click();
		expect(p.onUndo).toHaveBeenCalledWith('f@2017|u1');
	});

	it('a fetch failure offers retry', async () => {
		const p = base({ views: { 'f@2017|u1': { ...closed, open: true, error: 'unavailable' } } });
		render(CopilotPanel, p);
		await page.getByRole('button', { name: 'Retry' }).click();
		expect(p.onRetry).toHaveBeenCalledWith('f@2017|u1');
	});

	it('ask is scoped to the open card, else general; threads and General render', async () => {
		const p = base({ views: { 'f@2017|u1': { ...closed, open: true, entry } }, threads: { 'f@2017|u1': [{ question: 'Perifissural?', answer: 'No follow-up.' }] },
			general: [{ question: 'CBD?', answer: 'Up to 10 mm.' }] });
		render(CopilotPanel, p);
		await expect.element(page.getByText('Perifissural?')).toBeInTheDocument();
		await expect.element(page.getByText('Up to 10 mm.')).toBeInTheDocument();
		await expect.element(page.getByText('Asking about Fleischner 2017')).toBeInTheDocument();
		await page.getByRole('textbox', { name: 'Ask' }).fill('Does calcification matter?');
		await page.getByRole('button', { name: 'Send' }).click();
		expect(p.onAsk).toHaveBeenCalledWith('Does calcification matter?', 'f@2017|u1');
	});

	it('no cards and no answers: a quiet empty state', async () => {
		render(CopilotPanel, base({ cards: [], views: {} }));
		await expect.element(page.getByText(/Guidelines that apply to your findings appear here/)).toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/CopilotPanel.svelte.test.ts`
Expected: FAIL (no component).

- [ ] **Step 3: Write the component**

Use the classes agreed in Task 14. The sky tint shown below is the proposal and is replaced by whatever was agreed.

```svelte
<!-- frontend/src/lib/hybrid-stack/CopilotPanel.svelte -->
<script lang="ts">
	// Scratchpad Copilot panel (spec 2026-10-12-scratchpad-copilot §3-§4). Presentational: the scratchpad owns calls and
	// state. Cards are discovery; opening one reads; only Apply adds to the report. Missing inputs are neutral choice
	// buttons, never amber (amber means "the report needs your answer"). Enrichment tint: sky (Task 14 mock-up).
	import { fade, slide } from 'svelte/transition';
	import { cardId, type Finding } from './copilot';
	import type { CopilotCard, CopilotPreview, GuidelineEntry, QA } from './types';

	export type CardView = { open: boolean; loading: boolean; error: string | null; entry: GuidelineEntry | null;
		preview: CopilotPreview | null; answered: Record<string, string>; applied: boolean; previewing: boolean };

	let {
		cards, findings, views, threads, general, asking = false,
		onOpen, onClose, onInput, onApply, onUndo, onAsk, onRetry
	}: {
		cards: CopilotCard[]; findings: Finding[]; views: Record<string, CardView>; threads: Record<string, QA[]>; general: QA[];
		asking?: boolean;
		onOpen: (id: string) => void; onClose: (id: string) => void; onInput: (id: string, input: string, value: string) => void;
		onApply: (id: string) => void; onUndo: (id: string) => void; onAsk: (question: string, scope: string | null) => void;
		onRetry: (id: string) => void;
	} = $props();

	let question = $state('');
	const ms = 160;
	const label = (c: CopilotCard) => `${c.name}${c.version ? ' ' + c.version : ''}`;
	const findingText = (id: string) => findings.find((f) => f.id === id)?.text ?? '';
	const openCard = $derived(cards.find((c) => views[cardId(c)]?.open) ?? null);
	const scope = $derived(openCard ? cardId(openCard) : null);
	const byFinding = $derived(findings.map((f) => ({ f, cards: cards.filter((c) => c.finding_id === f.id) })).filter((g) => g.cards.length));
	const orphan = $derived(cards.filter((c) => !findings.some((f) => f.id === c.finding_id)));
	function send() {
		const q = question.trim();
		if (!q || asking) return;
		onAsk(q, scope);
		question = '';
	}
	const branchOf = (c: CopilotCard, v: CardView) => v.entry?.content.branches.find((b) => b.name === c.branch) ?? v.entry?.content.branches.find((b) => b.state === 'checked') ?? null;
</script>

<aside class="flex h-full flex-col gap-2 text-xs" aria-label="Copilot">
	<div class="flex-1 space-y-3 overflow-y-auto pr-1">
		{#if !cards.length && !general.length}
			<p class="px-1 italic text-gray-600">Guidelines that apply to your findings appear here. Ask anything below.</p>
		{/if}
		{#each [...byFinding, ...(orphan.length ? [{ f: { id: '', text: '', region: '' }, cards: orphan }] : [])] as g (g.f.id)}
			<section class="space-y-1">
				{#if g.f.text}<p class="truncate px-1 text-[10px] uppercase tracking-wide text-gray-500">{g.f.text}</p>{/if}
				{#each g.cards as c (cardId(c))}
					{@const id = cardId(c)}
					{@const v = views[id]}
					{@const br = v ? branchOf(c, v) : null}
					<div class="rounded border-l-2 border-sky-400/50 bg-sky-500/[0.04]" transition:fade={{ duration: ms }}>
						<button type="button" class="flex w-full items-baseline gap-2 px-2 py-1 text-left hover:bg-white/5"
							onclick={() => (v?.open ? onClose(id) : onOpen(id))}>
							<span class="text-gray-400">{v?.open ? '▾' : '▸'}</span>
							<span class="font-medium text-sky-100">{label(c)}</span>
							{#if c.why}<span class="truncate text-gray-500">{c.why}</span>{/if}
							{#if c.from_question}<span class="ml-auto shrink-0 text-[10px] text-gray-500">from your question</span>{/if}
							{#if (threads[id]?.length ?? 0) && !v?.open}<span class="ml-auto shrink-0 text-[10px] text-gray-500">{threads[id].length} {threads[id].length === 1 ? 'question' : 'questions'}</span>{/if}
						</button>
						{#if v?.open}
							<div class="space-y-1.5 px-2 pb-2" transition:slide={{ duration: ms }}>
								{#if v.loading}
									<p class="italic text-gray-500">Loading guideline…</p>
								{:else if v.error}
									<p class="flex gap-2 text-gray-400">Couldn't load this guideline.
										<button type="button" class="text-sky-200 hover:text-sky-100" onclick={() => onRetry(id)}>Retry</button></p>
								{:else if v.entry}
									{#if v.entry.content.summary}<p class="text-gray-300">{v.entry.content.summary}</p>{/if}
									{#if br && br.state !== 'checked'}
										<p class="italic text-gray-500">{br.state === 'pending' ? 'Still loading this part of the guideline…' : 'This part of the guideline could not be found in the sources.'}</p>
									{/if}
									{#each br?.inputs ?? [] as inp (inp.id)}
										{@const chosen = v.answered[inp.id] ?? v.preview?.settled.find((s) => s.input === inp.id)?.value}
										<div class="flex flex-wrap items-center gap-1">
											<span class="text-gray-400">{inp.question}</span>
											{#each inp.options as o (o)}
												<button type="button" class="rounded px-1.5 py-0.5 {chosen === o ? 'bg-white/15 text-gray-100' : 'bg-white/5 text-gray-400 hover:text-gray-200'}"
													aria-pressed={chosen === o} onclick={() => onInput(id, inp.id, o)}>{o}</button>
											{/each}
										</div>
									{/each}
									{#if v.preview?.proposal}
										<div class="rounded bg-white/[0.03] px-1.5 py-1">
											<p class="text-sky-100">{v.preview.proposal.classification}</p>
											{#if v.preview.proposal.recommendation}<p class="text-gray-300">{v.preview.proposal.recommendation}</p>{/if}
										</div>
									{:else if v.previewing}
										<p class="italic text-gray-500">Checking…</p>
									{/if}
									<div class="flex items-center gap-2">
										{#if v.applied}
											<span class="text-sky-200">Applied ✓</span>
											<button type="button" class="text-gray-400 hover:text-gray-200" onclick={() => onUndo(id)}>Undo</button>
										{:else}
											<button type="button" class="rounded bg-sky-500/20 px-2 py-0.5 text-sky-100 hover:bg-sky-500/30 disabled:cursor-not-allowed disabled:opacity-40"
												disabled={!v.preview?.proposal || v.previewing} onclick={() => onApply(id)}>Apply</button>
										{/if}
										{#if v.entry.status !== 'verified'}
											<span class="ml-auto text-[10px] text-gray-500" title={v.entry.sources.map((s) => s.url).join('\n')}>unverified · {v.entry.sources.length} {v.entry.sources.length === 1 ? 'source' : 'sources'}</span>
										{/if}
									</div>
									{#each v.entry.sources.slice(0, 3) as s (s.url)}
										<a class="block truncate text-[10px] text-gray-500 hover:text-gray-300" href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a>
									{/each}
								{/if}
								{#each threads[id] ?? [] as qa, k (k)}
									<div class="border-t border-white/5 pt-1">
										<p class="text-gray-300">{qa.question}</p>
										<p class="{qa.error ? 'text-rose-300/80' : 'text-gray-400'}">{qa.error ? "Couldn't answer. Ask again." : qa.answer}</p>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</section>
		{/each}
		{#if general.length}
			<section class="space-y-1">
				<p class="px-1 text-[10px] uppercase tracking-wide text-gray-500">General</p>
				{#each general as qa, k (k)}
					<div class="rounded bg-white/[0.02] px-2 py-1">
						<p class="text-gray-300">{qa.question}</p>
						<p class="{qa.error ? 'text-rose-300/80' : 'text-gray-400'}">{qa.error ? "Couldn't answer. Ask again." : qa.answer}</p>
					</div>
				{/each}
			</section>
		{/if}
	</div>
	<div class="shrink-0 space-y-1 border-t border-white/5 pt-2">
		{#if openCard}<p class="px-1 text-[10px] text-gray-500">Asking about {label(openCard)}</p>{/if}
		<div class="flex items-end gap-1">
			<textarea rows="1" aria-label="Ask" bind:value={question} placeholder={openCard ? 'Ask about this guideline…' : 'Ask…'}
				class="min-h-[2rem] flex-1 resize-none rounded border border-white/10 bg-transparent px-2 py-1 text-xs text-gray-200 outline-none placeholder:text-gray-600 focus:border-white/20"
				onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}></textarea>
			<button type="button" class="rounded px-2 py-1 text-gray-400 hover:text-gray-200 disabled:opacity-40" aria-label="Send" disabled={!question.trim() || asking} onclick={send}>
				{asking ? '…' : '↵'}
			</button>
		</div>
	</div>
</aside>
```

**Dictation into the ask box.** It uses the scratchpad's mic routing: when the textarea is focused, the scratchpad's
`stackEditing` path sends finals into it. Wire it in Task 19 with `onfocus`/`onblur` callbacks (`onEditing`). If
routing the finals is more than a small change there, ship typing first and add dictation as a follow-up task. Say so
in the Task 19 report.

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/CopilotPanel.svelte.test.ts`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hybrid-stack/CopilotPanel.svelte frontend/src/lib/hybrid-stack/CopilotPanel.svelte.test.ts
git commit -m "feat(copilot): side panel with card states, Apply gate, threads and ask"
```

---

### Task 18: Enrichment lines and the Recommendations checklist in `HybridStackView`

**Files:**
- Modify: `frontend/src/lib/hybrid-stack/HybridStackView.svelte`
- Test: `frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts` (additions)

- [ ] **Step 1: Write the failing test** (append inside the existing `describe`)

```ts
	it('applied guidelines show under their region with ×; the recommendations checklist ticks and adds', async () => {
		const props = { ...base(), onRemoveEnrichment: vi.fn(), onToggleRec: vi.fn(), onAddRec: vi.fn() };
		render(HybridStackView, {
			...props,
			units: [u(0, 'An 8 mm liver lesion.', 'Liver', { abnormal: true, covers: ['Liver'] })],
			enrichments: [{ key: 'x@1', version: '1', status: 'draft', finding_id: 'u0', region: 'Liver', line: 'LI-RADS 2018: LR-4.', recommendation: 'MRI in 3 months.' }],
			recommendations: [{ text: 'MRI in 3 months.', source: 'guideline', key: 'x@1', ticked: true }, { text: 'Refer to HPB MDT.', source: 'suggested', ticked: false }],
			showRecommendations: true
		});
		await expect.element(page.getByText('LI-RADS 2018: LR-4.')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Remove LI-RADS 2018: LR-4.' }).click();
		expect(props.onRemoveEnrichment).toHaveBeenCalledWith('x@1|u0');
		await expect.element(page.getByRole('checkbox', { name: 'MRI in 3 months.' })).toBeChecked();
		await page.getByRole('checkbox', { name: 'Refer to HPB MDT.' }).click();
		expect(props.onToggleRec).toHaveBeenCalledWith('Refer to HPB MDT.');
		await page.getByRole('textbox', { name: 'Add a recommendation' }).fill('Repeat US in 6 months.');
		await page.getByRole('textbox', { name: 'Add a recommendation' }).press('Enter');
		expect(props.onAddRec).toHaveBeenCalledWith('Repeat US in 6 months.');
	});
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/HybridStackView.svelte.test.ts -t "applied guidelines"`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add these props to the destructure and to the props type, with defaults:

```ts
		enrichments = [],
		recommendations = [],
		showRecommendations = false,
		onRemoveEnrichment = () => {},
		onToggleRec = () => {},
		onAddRec = () => {},
```

```ts
		enrichments?: Enrichment[];
		recommendations?: RecItem[];
		showRecommendations?: boolean; // the Copilot is on for this session
		onRemoveEnrichment?: (cardId: string) => void;
		onToggleRec?: (text: string) => void;
		onAddRec?: (text: string) => void;
```

Import `Enrichment` and `RecItem` from `./types`, and `cardId` from `./copilot`. Add `let newRec = $state('');`.

In the region `{#each shown as g (g.name)}` block, directly after
`<ul>{#each g.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>`:

```svelte
			{#each enrichments.filter((e) => e.region === g.name) as e (cardId(e))}
				<p class="mt-0.5 flex items-baseline gap-1.5 rounded border-l-2 border-sky-400/50 bg-sky-500/[0.04] px-1.5 py-0.5 text-xs" in:fade={{ duration: ms }} out:fade={{ duration: ms }} data-enrichment={e.key}>
					<svg viewBox="0 0 24 24" class="h-3 w-3 shrink-0 self-center text-sky-300/80" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>
					<span class="text-sky-100/90">{e.line}</span>
					<button type="button" class="ml-auto text-gray-500 hover:text-gray-300" aria-label="Remove {e.line}" onclick={() => onRemoveEnrichment(cardId(e))}>×</button>
				</p>
			{/each}
```

After the conclusion `</section>` and before the gate-bar comment:

```svelte
	{#if showRecommendations && (recommendations.length || hasConclusion)}
		<section aria-label="Recommendations" class="border-t border-white/5 pt-2">
			<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">Recommendations</h3>
			<ul class="mt-0.5 space-y-0.5 px-1">
				{#each recommendations as r (r.text)}
					<li class="flex items-baseline gap-2 text-sm leading-6" in:fade={{ duration: ms }}>
						<input type="checkbox" class="translate-y-0.5 accent-sky-400" checked={r.ticked} aria-label={r.text} onchange={() => onToggleRec(r.text)} />
						<span class={r.ticked ? 'text-gray-200' : 'text-gray-500'}>{r.text}</span>
						{#if r.source === 'guideline' && r.key}<span class="text-[10px] text-sky-300/70">{r.key.split('@')[0]}</span>{/if}
					</li>
				{/each}
			</ul>
			<input type="text" aria-label="Add a recommendation" placeholder="Add a recommendation…" bind:value={newRec}
				class="mt-1 w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-gray-300 outline-none placeholder:text-gray-600 focus:border-white/10"
				onkeydown={(e) => { if (e.key === 'Enter' && newRec.trim()) { onAddRec(newRec.trim()); newRec = ''; } }} />
		</section>
	{/if}
```

- [ ] **Step 4: Run all the view tests**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/HybridStackView.svelte.test.ts`
Expected: all pass, with the existing tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hybrid-stack/HybridStackView.svelte frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts
git commit -m "feat(copilot): enrichment lines under findings; Recommendations checklist under the conclusion"
```

---

### Task 19: Scratchpad integration

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`
- Modify: `frontend/src/routes/components/IntelliDictateTab.svelte` and `frontend/src/routes/components/TemplateForm.svelte`
  (pass `stackCopilot`)

The wiring follows the spec:
1. Match after `/group` settles.
2. Open, preview, Apply and Undo per card.
3. Apply and Undo count as a material change: the conclusion reacts and the recommendations redraw.
4. The draft reads the enrichments.
5. The gate carries enrichments and recommendations.
6. Logging.

- [ ] **Step 1: Add the prop and state** (near the other stack props and state)

```ts
	/** The scratchpad Copilot (spec 2026-10-12-scratchpad-copilot): guideline cards beside the scratchpad. */
	export let stackCopilot = false;
```

```ts
	// ── Copilot state (spec §4) ─────────────────────────────────────────────────────────────────────────────────────
	let copilotCards: CopilotCard[] = [];
	let copilotViews: Record<string, CardView> = {};
	let copilotThreads: Record<string, QA[]> = {};
	let copilotGeneral: QA[] = [];
	let copilotAsking = false;
	let enrichments: Enrichment[] = [];
	let recommendations: RecItem[] = [];
	let matchedFor = '';
	let matchTimer: ReturnType<typeof setTimeout> | null = null;
	let matchSeq = 0;
	let recsSeq = 0;
	let copilotLog = { matched: [] as string[], opened: [] as string[], applied: [] as string[], ms: {} as Record<string, number> };
	$: copilotOn = hybridStack && stackCopilot;
	$: copilotFindings = abnormalFindings(stackUnits);
	$: enrichments = pruneEnrichments(enrichments, copilotFindings);
```

Imports:
- from `$lib/hybrid-stack/copilot`: `abnormalFindings`, `cardId`, `enrichmentExtra`, `enrichmentLines`, `fileAnswer`,
  `mergeRecs`, `pruneEnrichments`, `upsertEnrichment`
- the types `CopilotCard`, `Enrichment`, `QA` and `RecItem`
- `postAsk`, `postMatch`, `postOpen`, `postPreview` and `postRecommendations` from the api
- `CopilotPanel` and `type CardView` from `$lib/hybrid-stack/CopilotPanel.svelte`

- [ ] **Step 2: Match after grouping settles**

Add the reactive trigger next to the other stack reactive blocks:

```ts
	$: if (copilotOn) scheduleMatch(copilotFindings.map((f) => `${f.id}\u0002${f.text}`).join('\u0003'));
	function scheduleMatch(key: string): void {
		if (key === matchedFor) return;
		if (matchTimer) clearTimeout(matchTimer);
		matchTimer = setTimeout(() => void runMatch(key), 900);
	}
	async function runMatch(key: string): Promise<void> {
		matchTimer = null;
		matchedFor = key;
		const seq = ++matchSeq;
		const findings = copilotFindings.map(({ id, text }) => ({ id, text }));
		if (!findings.length) {
			copilotCards = copilotCards.filter((c) => c.from_question);
			return;
		}
		try {
			const res = await postMatch($token, { scan_type: scanType, clinical_history: clinicalHistory, findings });
			if (seq !== matchSeq) return;
			const keep = copilotCards.filter((c) => c.from_question || enrichments.some((e) => cardId(e) === cardId(c)) || copilotViews[cardId(c)]?.open);
			const next = [...keep];
			for (const c of res.cards) if (!next.some((x) => cardId(x) === cardId(c))) next.push(c);
			copilotCards = next.filter((c) => c.from_question || copilotFindings.some((f) => f.id === c.finding_id));
			copilotLog.matched = [...new Set([...copilotLog.matched, ...res.cards.map((c) => c.key)])];
			copilotLog.ms.match = Math.max(copilotLog.ms.match ?? 0, res.ms);
		} catch {
			/* fails open: the cards on screen stay */
		}
	}
```

- [ ] **Step 3: Open, input, preview, apply, undo, retry**

```ts
	const findingTextOf = (id: string) => copilotFindings.find((f) => f.id === id)?.text ?? '';
	const viewOf = (id: string): CardView => copilotViews[id] ?? { open: false, loading: false, error: null, entry: null, preview: null, answered: {}, applied: false, previewing: false };
	function setView(id: string, patch: Partial<CardView>): void {
		copilotViews = { ...copilotViews, [id]: { ...viewOf(id), ...patch } };
	}
	async function copilotOpen(id: string): Promise<void> {
		const card = copilotCards.find((c) => cardId(c) === id);
		if (!card) return;
		const v = viewOf(id);
		setView(id, { open: true });
		if (v.entry) return; // already loaded this session
		setView(id, { loading: true, error: null });
		copilotLog.opened = [...new Set([...copilotLog.opened, card.key])];
		try {
			const res = await postOpen($token, { card, findings: findingTextOf(card.finding_id), clinical_history: clinicalHistory, answered: v.answered });
			setView(id, { loading: false, entry: res.entry, preview: res.preview, error: res.error });
			copilotLog.ms.open = Math.max(copilotLog.ms.open ?? 0, res.ms);
		} catch {
			setView(id, { loading: false, error: 'unavailable' });
		}
	}
	async function copilotInput(id: string, input: string, value: string): Promise<void> {
		const card = copilotCards.find((c) => cardId(c) === id);
		if (!card) return;
		const answered = { ...viewOf(id).answered, [input]: value };
		setView(id, { answered, previewing: true });
		try {
			const res = await postPreview($token, { card, findings: findingTextOf(card.finding_id), clinical_history: clinicalHistory, answered });
			if (JSON.stringify(viewOf(id).answered) === JSON.stringify(answered)) setView(id, { preview: res.preview, previewing: false });
		} catch {
			setView(id, { previewing: false });
		}
	}
	function copilotApply(id: string): void {
		const card = copilotCards.find((c) => cardId(c) === id);
		const v = viewOf(id);
		const p = v.preview?.proposal;
		const f = copilotFindings.find((x) => x.id === card?.finding_id);
		if (!card || !p || !f || !v.entry) return;
		const before = [...abnormalAll(stackUnits), ...enrichmentLines(enrichments)];
		enrichments = upsertEnrichment(enrichments, { key: card.key, version: card.version, status: v.entry.status, finding_id: f.id,
			region: f.region, line: p.line, recommendation: p.recommendation });
		setView(id, { applied: true });
		copilotLog.applied = [...new Set([...copilotLog.applied, card.key])];
		enrichmentChanged(before);
	}
	function copilotUndo(id: string): void {
		const before = [...abnormalAll(stackUnits), ...enrichmentLines(enrichments)];
		enrichments = enrichments.filter((e) => cardId(e) !== id);
		setView(id, { applied: false });
		enrichmentChanged(before);
	}
	/** Apply and remove are material changes (spec §2.10): the conclusion reacts, the recommendations redraw. */
	function enrichmentChanged(before: string[]): void {
		const after = [...abnormalAll(stackUnits), ...enrichmentLines(enrichments)];
		recommendations = mergeRecs(recommendations, enrichments, recommendations.filter((r) => r.source === 'suggested').map((r) => r.text));
		void reactConclusion(before, after);
		void refreshRecs();
	}
	async function refreshRecs(): Promise<void> {
		if (!copilotOn) return;
		const seq = ++recsSeq;
		const findings = findingsText(stackUnits, stackGroups, enrichmentExtra(enrichments));
		if (!findings.trim()) return;
		try {
			const res = await postRecommendations($token, { scan_type: scanType, clinical_history: clinicalHistory, findings,
				conclusion: dictatedConclusion || draft?.text || '', applied: enrichments.map((e) => e.recommendation).filter(Boolean) });
			if (seq !== recsSeq) return;
			recommendations = mergeRecs(recommendations, enrichments, res.items);
		} catch {
			/* fails open: applied items still show */
		}
	}
	function toggleRec(text: string): void {
		recommendations = recommendations.map((r) => (r.text === text ? { ...r, ticked: !r.ticked } : r));
	}
	function addRec(text: string): void {
		if (recommendations.some((r) => r.text.trim().toLowerCase() === text.trim().toLowerCase())) return;
		recommendations = [...recommendations, { text, source: 'typed', ticked: true }];
	}
	async function copilotAsk(question: string, scope: string | null): Promise<void> {
		copilotAsking = true;
		const scoped = scope ? copilotCards.find((c) => cardId(c) === scope) : null;
		const history = scope ? copilotThreads[scope] ?? [] : copilotGeneral;
		try {
			const res = await postAsk($token, { question, key: scoped?.key ?? null, finding_id: scoped?.finding_id ?? copilotFindings[0]?.id ?? '',
				scan_type: scanType, clinical_history: clinicalHistory, findings: findingsText(stackUnits, stackGroups), history });
			const s = fileAnswer({ cards: copilotCards, threads: copilotThreads, general: copilotGeneral }, scope, res, question);
			copilotCards = s.cards; copilotThreads = s.threads; copilotGeneral = s.general;
			if (!scope && res.card) {
				const id = cardId(s.cards.find((c) => c.key === res.card!.key)!);
				setView(id, { open: true, entry: res.entry ?? viewOf(id).entry });
				if (!viewOf(id).preview) void copilotOpen(id); // fills the preview for this case
			}
		} catch {
			const s = fileAnswer({ cards: copilotCards, threads: copilotThreads, general: copilotGeneral }, scope,
				{ kind: scope ? 'card' : 'general', answer: '', key: null, card: null, entry: null, searched: false, supported: false, error: 'failed' }, question);
			copilotThreads = s.threads; copilotGeneral = s.general;
		} finally {
			copilotAsking = false;
		}
	}
```

- [ ] **Step 4: The draft, the conclusion and the gate read enrichments**

- In `requestDraft` and `suggestConclusion`, replace `findingsText(stackUnits, stackGroups)` with
  `findingsText(stackUnits, stackGroups, enrichmentExtra(enrichments))`.
- After a draft lands in `requestDraft`, inside the `if (res.text)` branch, add `void refreshRecs();`.
- In `stackConfirm`, add these to the `gate` literal:

```ts
			enrichments: copilotOn ? enrichments : undefined,
			recommendations: copilotOn ? recommendations : undefined,
```

- Add enrichments and recommendations to `gateKey`, so a change after Confirm re-arms the gate. Append to the array
  before `.join('\u0003')`:

```ts
		JSON.stringify(enrichments.map((e) => cardId(e) + e.line)), JSON.stringify(recommendations.map((r) => r.text + (r.ticked ? '1' : '0')))
```

- In `sendStackLog`, add to the payload:
  `copilot: copilotOn ? { ...copilotLog, threads: copilotThreads, general: copilotGeneral, recommendations } : null`.
  Add `copilot?: Record<string, unknown> | null` to the `StackLog` interface in `api.ts`.
- In `resetStack`, clear `copilotCards`, `copilotViews`, `copilotThreads`, `copilotGeneral`, `enrichments`,
  `recommendations`, `matchedFor` and `copilotLog`.

- [ ] **Step 5: Mount the panel and pass the view props**

Replace the margin column's width expression:

```svelte
					style="width: {copilotOn && stackView ? '320px' : activePrompts.length > 0 && !stackView ? '240px' : '0px'}; transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1)"
```

Inside that column, render the panel or the existing margin:

```svelte
					{#if copilotOn && stackView}
						<div class="h-full border-l border-white/5 pl-2">
							<CopilotPanel cards={copilotCards} findings={copilotFindings} views={copilotViews} threads={copilotThreads} general={copilotGeneral}
								asking={copilotAsking} onOpen={copilotOpen} onClose={(id) => setView(id, { open: false })} onInput={copilotInput}
								onApply={copilotApply} onUndo={copilotUndo} onAsk={copilotAsk}
								onRetry={(id) => { setView(id, { entry: null, error: null }); void copilotOpen(id); }} />
						</div>
					{:else}
						<IntelliPromptsMargin … unchanged … />
					{/if}
```

Add to the `<HybridStackView …>` props:

```svelte
							enrichments={copilotOn ? enrichments : []} recommendations={recommendations} showRecommendations={copilotOn}
							onRemoveEnrichment={copilotUndo} onToggleRec={toggleRec} onAddRec={addRec}
```

- [ ] **Step 6: Pass the flag from both parents**

In `IntelliDictateTab.svelte` and `TemplateForm.svelte`, on the `<DictationScratchpad …>` element:

```svelte
			stackCopilot={stackStatus?.stack_copilot === true}
```

Extend each file's `stackStatus` type to include `stack_copilot?: boolean`.

- [ ] **Step 7: Type check and run the stack test suites**

Run: `cd frontend && npm run check && npx vitest run src/lib/hybrid-stack`
Expected: no new type errors, and all hybrid-stack tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte frontend/src/lib/hybrid-stack/api.ts \
  frontend/src/routes/components/IntelliDictateTab.svelte frontend/src/routes/components/TemplateForm.svelte
git commit -m "feat(copilot): scratchpad wiring — match, open, apply, ask, recommendations, gate and log"
```

---

### Task 20: `/stack-guidelines` review page

**Files:**
- Create: `frontend/src/routes/stack-guidelines/+page.svelte`

- [ ] **Step 1: Write the page**

It follows `routes/stack-families/+page.svelte`: a production review page that the server gates to reviewers.

```svelte
<!-- frontend/src/routes/stack-guidelines/+page.svelte -->
<script lang="ts">
	// Guideline registry review (scratchpad copilot spec §5.1). Not a dev route: entries live in production; the server
	// allows only RR_STACK_REVIEWERS (403 otherwise). Check every branch's outputs against its quote and sources, and
	// coverage (branches not_available or pending), then verify, edit the JSON, or discard (the next open re-fetches).
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config.js';
	import { token } from '$lib/stores/auth';
	import type { GuidelineEntry } from '$lib/hybrid-stack/types';

	type Row = GuidelineEntry & { chunks: { url: string; text: string; branch: string }[]; updated_at: string | null };
	let rows: Row[] = $state([]);
	let error = $state('');
	let edits: Record<string, string> = $state({});
	let showChunks: Record<string, boolean> = $state({});
	const headers = (): Record<string, string> => ({ 'Content-Type': 'application/json', ...($token ? { Authorization: `Bearer ${$token}` } : {}) });

	async function load() {
		const res = await fetch(`${API_URL}/api/canvas/stack/guidelines/registry`, { headers: headers() });
		if (!res.ok) {
			error = res.status === 403 ? 'Not a reviewer.' : `Error ${res.status}`;
			return;
		}
		rows = await res.json();
		edits = Object.fromEntries(rows.map((r) => [r.key, JSON.stringify(r.content, null, 1)]));
	}
	async function update(key: string, status: 'verified' | 'draft' | 'discarded', withContent: boolean) {
		const body: Record<string, unknown> = { status };
		if (withContent) {
			try {
				body.content = JSON.parse(edits[key]);
			} catch {
				error = `The content for ${key} is not valid JSON.`;
				return;
			}
		}
		const res = await fetch(`${API_URL}/api/canvas/stack/guidelines/registry/${encodeURIComponent(key)}`, { method: 'POST', headers: headers(), body: JSON.stringify(body) });
		if (res.ok) await load();
		else error = `Could not update ${key} (${res.status}).`;
	}
	onMount(load);
</script>

<div class="mx-auto max-w-5xl space-y-4 p-6 text-sm text-gray-200">
	<h1 class="text-lg font-semibold">Guideline registry</h1>
	{#if error}<p class="text-rose-300">{error}</p>{/if}
	{#each rows as r (r.key)}
		<section class="space-y-2 rounded-lg border border-white/10 p-3">
			<header class="flex flex-wrap items-baseline gap-2">
				<h2 class="font-medium">{r.name} {r.version}</h2>
				<code class="text-xs text-gray-500">{r.key}</code>
				<span class="rounded px-1.5 text-xs {r.status === 'verified' ? 'bg-emerald-500/15 text-emerald-200' : 'bg-white/5 text-gray-400'}">{r.status}</span>
			</header>
			<p class="text-gray-400">{r.content.summary}</p>
			{#each r.content.branches as b (b.name)}
				<div class="rounded bg-white/[0.02] p-2">
					<p class="font-medium">{b.name} <span class="text-xs {b.state === 'checked' ? 'text-emerald-300' : 'text-amber-300'}">{b.state}</span></p>
					{#if b.rule}<p class="text-xs text-gray-400">{b.rule}</p>{/if}
					<ul class="mt-1 space-y-1 text-xs">
						{#each b.outputs as o, k (k)}
							<li><span class="text-gray-300">{o.when} → {o.classification} {o.recommendation}</span><br /><span class="italic text-gray-500">“{o.quote}”</span></li>
						{/each}
					</ul>
				</div>
			{/each}
			<ul class="text-xs">{#each r.sources as s (s.url)}<li><a class="text-sky-300 hover:underline" href={s.url} target="_blank" rel="noreferrer">tier {s.tier} · {s.title || s.url}</a></li>{/each}</ul>
			<button type="button" class="text-xs text-gray-400 hover:text-gray-200" onclick={() => (showChunks[r.key] = !showChunks[r.key])}>{showChunks[r.key] ? 'Hide' : 'Show'} source text ({r.chunks.length})</button>
			{#if showChunks[r.key]}{#each r.chunks as c, k (k)}<pre class="max-h-60 overflow-auto whitespace-pre-wrap rounded bg-black/30 p-2 text-[11px] text-gray-400">{c.branch ? `[${c.branch}] ` : ''}{c.url}\n{c.text}</pre>{/each}{/if}
			<textarea class="h-40 w-full rounded border border-white/10 bg-black/20 p-2 font-mono text-[11px]" bind:value={edits[r.key]}></textarea>
			<div class="flex gap-2 text-xs">
				<button type="button" class="rounded bg-emerald-600/30 px-2 py-1" onclick={() => update(r.key, 'verified', true)}>Verify (with edits)</button>
				<button type="button" class="rounded bg-white/5 px-2 py-1" onclick={() => update(r.key, 'draft', true)}>Save as draft</button>
				<button type="button" class="rounded bg-rose-600/30 px-2 py-1" onclick={() => update(r.key, 'discarded', false)}>Discard</button>
			</div>
		</section>
	{/each}
</div>
```

- [ ] **Step 2: Type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/stack-guidelines/+page.svelte
git commit -m "feat(copilot): guideline registry review page"
```

---

# Phase D: verification

### Task 21: Full suites, a local end-to-end hand read, and independent review

- [ ] **Step 1: Full suites**

Run: `cd backend && PYTHONPATH=src poetry run pytest -q`
Then: `cd frontend && npm run check && npx vitest run`
Expected: everything passes. Record any failure that existed before this branch (compare with `feat/hybrid-stack`)
rather than fixing unrelated tests.

- [ ] **Step 2: Local end-to-end**

Use the `run` skill, or the local recipe from memory: `PYTHONPATH=src RR_DICTATION_V2=1` uvicorn plus the frontend dev
server, and drive the Chrome session. The automation tab is hidden, so verify state, not lingering DOM.

**Quick report, with a dictation that has a guideline-bearing finding and a benign one.** Check each of these:
1. Cards appear about 1 s after the finding lands, and none appear for the benign finding.
2. Opening a registry card takes about 1–2 s. Opening a new guideline takes about 5–10 s, then the panel shows
   "unverified".
3. Answering an input enables Apply. Apply adds the sky line under the finding, the conclusion draft redraws to name
   the classification where it changes management, and the recommendation appears ticked.
4. × on the line removes both.
5. Ticking a suggestion. Typing a recommendation.
6. A card-scoped question goes into the thread. A general guideline question adds a card "from your question". A
   general question with no guideline lands in General.
7. Confirm, then Generate. The report has the classification sentence in that finding's paragraph and a
   RECOMMENDATIONS section with only the ticked items.

**Template report, same dictation.** Check where the labelled recommendations line ends up in the generated report.
Record it for Hassan.

Then confirm that `RR_STACK_COPILOT=0` hides the panel and makes no copilot calls.

- [ ] **Step 3: Write up the hand read**

Write `<scratchpad>/copilot_lab/e2e_hand_read.md` covering both reports, with latencies and any defects. Fix defects
in small commits, each with a test where one fits.

- [ ] **Step 4: Independent review (required before merge)**

Dispatch `superpowers:code-reviewer` on the branch diff against `feat/hybrid-stack`, with the spec and plan paths.
Fix the confirmed findings. If the reviewer can't run, **stop and ask Hassan before merging** (memory: review before
merge).

- [ ] **Step 5: Push the branch and report to Hassan**

```bash
git push -u origin feat/scratchpad-copilot
```

Report:
- the lab summaries;
- the e2e hand read;
- the review outcome;
- the template-path note;
- deploy steps: Railway migration `20261012150000`, `TAVILY_API_KEY` present, seeds verified on `/stack-guidelines`.

Merge only on Hassan's go-ahead. It goes out with the new scratchpad layout (PR #31's line).

---

## Self-review notes

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2.1–2.16 | 16–19 (behaviour), 10 (kill switch), 21 (rollout note) |
| §2.17–2.21 | 3–5, 8 |
| §4.1 | 17, 19 |
| §4.2 | 18 |
| §4.3 | 16, 17, 19 |
| §4.4 | 9, 16, 18, 19 |
| §5.1 | 2, 20 |
| §5.2 | 6 |
| §5.3 | 4, 5 |
| §5.4 | 7, 10 |
| §5.5 | 8 |
| §5.6 | 9 |
| §5.7 | 2, 10, 19 |
| §5.8 TNM | 5b, 6, 7, 8, 13 |
| §6 | 11, 16, 19 |
| §7 | the fail-open tests in 5–10 and 19 |
| §8 labs | 12, 13 |
| §8 code tests | in every task |

**Known judgement points for the implementer (report them, don't silently change them):**
- **Task 12:** whether the local migration needs to be applied by hand.
- **Task 17/19:** whether ask-box dictation fits in Task 19 or becomes a follow-up.
- **Task 16:** the circular import between `copilot.ts` and `regionState.ts`. Split it out if the bundler warns.
