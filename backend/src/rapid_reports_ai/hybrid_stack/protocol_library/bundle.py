"""Load and validate the runtime bundle (spec §7). Never raises at request time: a missing or broken bundle turns the
library off and quick reports keep the free-text path."""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr

logger = logging.getLogger(__name__)
PIN_FILE = Path(__file__).resolve().parents[4] / "protocol_library.pin"


def phase_id(phases: list[str]) -> str:
    return "+".join(phases) or "none"


class LibRegion(BaseModel):
    name: str
    includes: str
    quiet: bool = False
    level_group: str | None = None


class Entry(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    modality: str
    laterality: str = "none"          # none | required
    agent: str
    phases_default: list[str] = Field(default_factory=list)
    phase_variants: list[list[str]] = Field(default_factory=list)
    coverage: str = ""
    not_assessable: list[str] = Field(default_factory=list)
    sheet_key: str
    contrast_class: str
    tier: str = "low"
    focus: str | None = None

    def phase_sets(self) -> list[list[str]]:
        out = [self.phases_default]
        for v in self.phase_variants:
            if v not in out:
                out.append(v)
        return out


class KeyDef(BaseModel):
    modality: str | None = None
    regions: list[LibRegion]
    level_groups: dict[str, list[str]] = Field(default_factory=dict)


class BaseSheet(BaseModel):
    markdown: str
    region_normals: dict[str, list[str]] = Field(default_factory=dict)
    not_assessable: str = ""
    status: str = "provisional"


class PhaseSheet(BaseModel):
    scan_context: dict[str, str] = Field(default_factory=dict)
    changed_normals: dict[str, list[str]] = Field(default_factory=dict)
    status: str = "provisional"


class Bundle(BaseModel):
    version: str
    generated_at: str = ""
    entries: list[Entry]
    keys: dict[str, KeyDef]
    base_sheets: dict[str, BaseSheet]
    phase_sheets: dict[str, PhaseSheet]
    _by_id: dict[str, Entry] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _ctx) -> None:
        self._by_id = {e.id: e for e in self.entries}

    def entry(self, entry_id: str) -> Entry | None:
        return self._by_id.get(entry_id)


class BundleError(ValueError):
    pass


def _validate(b: Bundle) -> None:
    problems = []
    for e in b.entries:
        if e.sheet_key not in b.keys:
            problems.append(f"{e.id}: unknown sheet key {e.sheet_key}")
            continue
        if f"{e.sheet_key}|{e.contrast_class}" not in b.base_sheets:
            problems.append(f"{e.id}: no base sheet {e.sheet_key}|{e.contrast_class}")
        for ph in e.phase_sets():
            if f"{e.id}|{phase_id(ph)}" not in b.phase_sheets:
                problems.append(f"{e.id}: no phase sheet {phase_id(ph)}")
    for k, kd in b.keys.items():
        names = [r.name for r in kd.regions]
        if len(set(names)) != len(names):
            problems.append(f"{k}: duplicate region names")
    if problems:
        raise BundleError("; ".join(problems[:20]))


def load_bundle(path: Path) -> Bundle:
    try:
        b = Bundle.model_validate(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as e:
        raise BundleError(f"cannot read {path}: {type(e).__name__}: {str(e)[:200]}") from e
    _validate(b)
    return b


_CACHE: dict[str, Bundle | None] = {}


def _resolve_path(raw: str) -> Path:
    p = Path(raw).expanduser()
    return p / "bundle" / "protocol_library.json" if p.is_dir() else p


def get_bundle(env: Mapping[str, str] = os.environ) -> Bundle | None:
    raw = env.get("RR_PROTOCOL_LIBRARY_PATH", "")
    if not raw:
        return None
    if raw in _CACHE:
        return _CACHE[raw]
    try:
        b = load_bundle(_resolve_path(raw))
        pin = PIN_FILE.read_text().strip() if PIN_FILE.exists() else ""
        if pin and not b.version.startswith(pin):
            logger.warning("[protocol_library] bundle %s does not match pin %s", b.version, pin)
        logger.info("[protocol_library] loaded bundle %s (%d entries)", b.version, len(b.entries))
    except BundleError as e:
        logger.warning("[protocol_library] protocol library off: %s", e)
        b = None
    _CACHE[raw] = b
    return b


def reset_cache() -> None:
    _CACHE.clear()


def library_allowed(env: Mapping[str, str] = os.environ) -> bool:
    from ..routes import stack_allowed
    return env.get("RR_PROTOCOL_LIBRARY") == "1" and stack_allowed(env) and get_bundle(env) is not None
