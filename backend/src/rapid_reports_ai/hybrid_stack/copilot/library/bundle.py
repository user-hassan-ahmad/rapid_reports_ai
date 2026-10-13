"""The compiled guideline library (library spec §4, §6). guidelines/<entry>/ is compiled, through the quality gates,
into one versioned bundle committed under resources/. The backend loads that bundle once and never reads the source
folders or the network. A bundle that fails to load gives an empty library: the Copilot shows no pack cards, and
nothing else is affected."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..registry import _strip_version, norm
from . import engine
from .schema import DOES_NOT_APPLY, Cases, Entry, InputDef, Manifest
from .verify import check

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve()
BUNDLE = _HERE.parents[3] / "resources" / "guideline_bundle.json"
_PUBLIC = ("id", "role", "title", "issuer", "edition", "url")
KNOWN_ALIASES = 3     # aliases shown per KNOWN SYSTEMS line (find still matches every alias)


def guidelines_root(here: Path = _HERE) -> Path:
    """The repo's guidelines/ folder, resolved only when compiling. A deploy layout shallower than the repo has no
    such folder; it gets a path that does not exist (an empty compile) rather than an IndexError at import."""
    parents = here.parents
    return parents[6] / "guidelines" if len(parents) > 6 else parents[-1] / "missing-guidelines"


class BundleError(Exception):
    pass


def _read(d: Path) -> list[tuple[Entry, Manifest, Cases | None]]:
    m = Manifest.model_validate_json((d / "manifest.json").read_text())
    c = Cases.model_validate_json((d / "cases.json").read_text()) if (d / "cases.json").exists() else None
    out = [(Entry.model_validate_json((d / "entry.json").read_text()), m, c)]
    hist = d / "history"
    out += [(Entry.model_validate_json(h.read_text()), m, None) for h in sorted(hist.glob("*.json"))] if hist.exists() else []
    return out


def compile_bundle(root: Path | None = None) -> dict[str, Any]:
    root = guidelines_root() if root is None else root
    entries: dict[str, Any] = {}
    problems: list[str] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        try:
            loaded = _read(d)
        except (OSError, ValidationError) as ex:
            problems.append(f"{d.name}: {ex}")
            continue
        for n, (e, m, c) in enumerate(loaded):
            if n == 0:
                if e.id != d.name:
                    problems.append(f"{d.name}: entry id {e.id} does not match its folder")
                if e.status != "current":
                    problems.append(f"{d.name}: entry.json must be the current version")
                problems += [f"{e.key}: {x}" for x in check(e, m, c)]
            elif e.status != "superseded":
                problems.append(f"{e.key}: a history version must be superseded")
            if e.key in entries:
                problems.append(f"{e.key}: duplicate version")
            entries[e.key] = {"entry": e.model_dump(mode="json", by_alias=True, exclude_none=True),
                              "sources": [s.model_dump(include=set(_PUBLIC)) for s in m.sources]}
    if problems:
        raise BundleError("\n".join(problems))
    body = json.dumps(entries, sort_keys=True, ensure_ascii=False)
    return {"version": hashlib.sha256(body.encode()).hexdigest()[:12], "entries": entries}


def dumps(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def _bare_display(e: Entry) -> str:
    """The display, normalised, with its edition token removed ("ESE adrenal incidentaloma 2023" -> "ese adrenal
    incidentaloma"): the form the matcher is told to give, a name without the version."""
    d, ed = norm(e.display), norm(e.edition)
    return " ".join(re.sub(rf"\b{re.escape(ed)}\b", " ", d).split()) if ed else d


def _names(e: Entry) -> set[str]:
    """Every normalised name `find` takes for an entry: display, system, aliases, the id as a slug, the key, and the
    display without its edition (as registry.alias_hit does for a registry row)."""
    return {n for n in (*(norm(x) for x in (e.display, e.system, *e.aliases, e.id.replace("-", " "), e.key)),
                        _bare_display(e)) if n}


def _excluding(e: Entry, i: InputDef) -> list:
    """The values of an eligibility input that, given alone, reach the does_not_apply outcome ([] if the engine
    refuses one: the scope line then omits the input rather than failing the prompt)."""
    try:
        return [v.value for v in engine.domain(e, i) or []
                if v.state == "present" and engine.evaluate(e, {i.id: v}).outcome == DOES_NOT_APPLY]
    except Exception:
        return []


def scope_line(e: Entry) -> str:
    """A one-line scope from the entry's own data only: applies_to (finding type, region, context, modality), then
    the eligibility inputs whose value alone removes the pack: "only:" a boolean that must hold (or the enum options
    that remain), "not:" a boolean that must not. Numbers are left out (a cut-off is not a clean one-line clause)."""
    a = e.applies_to
    s = " or ".join(a.finding_type) or e.topic
    s += f" in {'/'.join(a.region)}" if a.region else ""
    s += "".join(f", {'/'.join(x)}" for x in (a.context, a.modality) if x)
    only: list[str] = []
    nots: list[str] = []
    for i in e.inputs:
        if i.role != "eligibility" or i.type == "number" or e.tier != 1:
            continue
        x = _excluding(e, i)
        if i.type == "boolean" and x == [True]:
            nots.append(i.label)
        elif i.type == "boolean" and x == [False]:
            only.append(i.label)
        elif i.type == "enum" and x and (rest := [o for o in i.options if o not in x]):
            only.append(f"{i.label} = {'/'.join(rest)}")
    s += f"; only: {'; '.join(only)}" if only else ""
    s += f"; not: {'; '.join(nots)}" if nots else ""
    return s


class Library:
    def __init__(self, bundle: dict[str, Any]):
        raw = bundle.get("entries", {})
        self._version = bundle.get("version", "")
        self._entries = {k: Entry.model_validate(v["entry"]) for k, v in raw.items()}
        self._sources = {k: v.get("sources", []) for k, v in raw.items()}
        self._known: str | None = None

    def version(self) -> str:
        return self._version

    def _current(self) -> list[Entry]:
        return sorted((e for e in self._entries.values() if e.status == "current"), key=lambda e: e.id)

    def lookup(self, key_or_id: str, version: str | None = None) -> Entry | None:
        if "@" in key_or_id:
            return self._entries.get(key_or_id)
        if version is not None:
            return self._entries.get(f"{key_or_id}@{version}")
        return next((e for e in self._current() if e.id == key_or_id), None)

    def list(self, region: str | None = None, modality: str | None = None, finding_type: str | None = None,
             context: str | None = None) -> list[Entry]:
        want = {"region": region, "modality": modality, "finding_type": finding_type, "context": context}
        return [e for e in self._current()
                if all(v is None or v in getattr(e.applies_to, k) for k, v in want.items())]

    def siblings(self, entry: Entry) -> list[Entry]:
        return [e for e in self._current() if e.topic == entry.topic and e.id != entry.id]

    def find(self, name: str, version: str = "") -> Entry | None:
        """The current entry a model-named system is: its display (with or without its edition), system name, an
        alias, its id as a slug or its key, normalised, or the same with a trailing version token stripped; a version,
        when given, must equal the edition. Exactly one hit, never a guess between siblings."""
        n = norm(name)
        if not n:
            return None
        ns = _strip_version(n)
        hits = [e for e in self._current() if n in (names := _names(e)) or (ns and ns in names)]
        if version:
            hits = [e for e in hits if norm(e.edition) == norm(version)]
        return hits[0] if len(hits) == 1 else None

    def sources(self, key: str) -> list[dict]:
        return list(self._sources.get(key, []))

    def evaluate(self, key: str, given: dict[str, Any]) -> engine.Trace:
        e = self.lookup(key)
        if e is None or e.tier != 1:
            raise KeyError(key)
        return engine.evaluate(e, given)

    def known_text(self) -> str:
        """Lines for the matcher prompt's KNOWN SYSTEMS block (both tiers): `- key: display [aliases: ...] (scope:
        ...)`, the model picking a pack by its key from the scope and the finding."""
        if self._known is None:   # the scope runs the engine per eligibility value: built once per bundle
            self._known = "\n".join(f"- {e.key}: {e.display} [aliases: {' | '.join(e.aliases[:KNOWN_ALIASES])}] "
                                     f"(scope: {scope_line(e)})" for e in self._current())
        return self._known


@lru_cache(maxsize=1)
def _load() -> Library:
    try:
        return Library(json.loads(BUNDLE.read_text()))
    except Exception as ex:   # fail open: no pack cards, nothing else affected
        logger.error("[library] bundle failed to load (%s): %s", type(ex).__name__, str(ex)[:200])
        return Library({})


def get() -> Library:
    return _load()
