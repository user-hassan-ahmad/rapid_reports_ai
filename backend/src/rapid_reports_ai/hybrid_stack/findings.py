"""The one findings builder (integration spec §5 Builder): a port of frontend regionState.ts findingsText and
buildFindingsBlock, held byte-identical by tests/fixtures/stack_golden.json. `block` is what the writer reads;
`plain()` is what the check, the description, the stored FINDINGS and the review engine read: the radiologist's
statements without labels, never a removed sentence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from .gate_model import GateRecord
from .schemas import CONCLUSION, GENERAL, TECHNIQUE
from .units import StackUnit

FIXED = {TECHNIQUE, GENERAL, CONCLUSION}
ANSWERED = "Answered by the radiologist:"
ASSUMED = "Assumed normal (confirmed by the radiologist):"


@dataclass(frozen=True)
class _Item:
    unit_id: int
    text: str
    group: str
    abnormal: bool


def _items(units: list[StackUnit]) -> list[_Item]:
    """A split unit contributes its parts, any other unit itself; headings and unplaced units nothing."""
    out: list[_Item] = []
    for u in units:
        if u.heading or u.group is None:
            continue
        if u.parts and len(u.parts) > 1:
            out += [_Item(u.id, p.text, p.group, bool(p.abnormal)) for p in u.parts]
        else:
            out.append(_Item(u.id, u.text, u.group, bool(u.abnormal)))
    return out


def findings_text(units: list[StackUnit], groups: list[str], extra: dict[str, list[str]] | None = None) -> str:
    """The grouped findings text (gate-less: /stack/draft and the Copilot routes). `extra`: labelled lines appended to
    a region's line; a region with only extra lines still gets its line."""
    extra = extra or {}
    # A sentence spanning regions goes whole, once, under its joined label
    spanning = [u for u in units if not u.heading and u.group is not None and u.parts and len(u.parts) > 1]
    span_ids = {u.id for u in spanning}
    items = [i for i in _items(units) if i.unit_id not in span_ids]
    lines: list[str] = []
    tech = [i.text for i in items if i.group == TECHNIQUE]
    if tech:
        lines += [" ".join(tech), ""]
    for g in groups:
        if g in FIXED:
            continue
        own = [i.text for i in items if i.group == g]
        more = extra.get(g, [])
        if own or more:
            lines.append(f"{g}: {' '.join([*own, *more])}")
    for g in dict.fromkeys(i.group for i in items):
        if g not in groups and g not in FIXED:
            lines.append(f"{g}: {' '.join(i.text for i in items if i.group == g)}")
    for u in spanning:
        spans = list(dict.fromkeys(p.group for p in (u.parts or [])))
        ordered = [g for g in groups if g in spans] + [g for g in spans if g not in groups]
        lines.append(f"{' · '.join(ordered)}: {u.text}")
    lines += [i.text for i in items if i.group == GENERAL]
    # Fail open: a sentence the grouper never placed still reaches the report, as said
    lines += [u.text for u in units if u.group is None and not u.heading]
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class Statements:
    block: str
    parts: list[str] = field(default_factory=list)   # plain statements, no labels, no removed sentence
    conclusion: str = ""
    said_parts: list[str] = field(default_factory=list)   # the radiologist's own units and tapped rows only

    def said(self) -> str:
        """What may override an earlier removal (D12, spec §7 step 0): dictated units and tapped rows, never an
        assumed normal, a value or the conclusion."""
        return "\n".join(p for p in self.said_parts if p.strip())

    def plain(self) -> str:
        return "\n".join(p for p in self.parts if p.strip())

    def all_texts(self) -> list[str]:
        return [p for p in self.parts if p.strip()]


def _value_statements(gate: GateRecord) -> list[str]:
    """Only values the radiologist typed; a filled value reaches the report through the dictation alone."""
    return [f"{c.item} {c.value}" for c in (gate.values or []) if c.state == "entered" and c.value]


def findings_block(units: list[StackUnit], groups: list[str], gate: GateRecord,
                   removed: list[str] | None = None) -> Statements:
    """What Generate receives (checklist spec §7): the radiologist's sentences, tapped rows, confirmed region normals,
    typed values, the confirmed conclusion, and what they removed (never to be asserted). `removed`: the reconciled
    list (dictation wins), else the gate's."""
    removed_list = list(gate.removed if removed is None else removed)
    items = _items(units)

    def dictated(r: str) -> bool:
        return any(i.group == r for i in items)

    extra: dict[str, list[str]] = {}
    standalone: list[str] = []
    plain: list[str] = [i.text for i in items if i.group != CONCLUSION]
    plain += [u.text for u in units if u.group is None and not u.heading]
    said = list(plain)
    for it in gate.items:
        if it.answered_by != "tap" or not it.sentences:
            continue
        plain += it.sentences
        said += it.sentences
        if it.region in groups and (dictated(it.region) or it.kind != "referral"):
            extra.setdefault(it.region, []).append(f"{ANSWERED} {' '.join(it.sentences)}")
        else:
            standalone.append(f"{it.region or 'Referral question'} (answered by the radiologist): "
                              f"{' '.join(it.sentences)}")
    tray: list[str] = []
    for r, sentences in gate.assumed.items():
        if not sentences:
            continue
        plain += sentences
        if dictated(r):
            extra.setdefault(r, []).append(f"{ASSUMED} {' '.join(sentences)}")
        else:
            tray.append(f"{r}: {' '.join(sentences)}")
    parts = [findings_text(units, groups, extra), "\n".join(standalone)]
    values = _value_statements(gate)
    if values:
        parts.append(f"{ANSWERED} {' '.join(v + '.' for v in values)}")
        plain += [v + "." for v in values]
    if tray:
        parts.append(f"{ASSUMED} {' '.join(tray)}")
    # Regions with no sentences to confirm: confirmed by name (the block only; names are not statements)
    named = [r for r in gate.assumed_normal if not gate.assumed.get(r)] + \
            [f"remainder of {r}" for r in gate.remainder_normal if not gate.assumed.get(r)]
    if named:
        parts.append(f"Confirmed normal (not dictated; confirmed by the radiologist): {'; '.join(named)}.")
    conclusion = gate.conclusion_text.strip()
    if conclusion:
        parts.append(f"Conclusion (confirmed by the radiologist): {conclusion}")
        plain.append(conclusion)
    if removed_list:
        parts.append(f"DO NOT ASSERT (removed by the radiologist): {' '.join(removed_list)}")
    gone = set(removed_list)
    return Statements(block="\n\n".join(p for p in parts if p),
                      parts=[p for p in plain if p not in gone], conclusion=conclusion, said_parts=said)


class FromUnits(BaseModel):
    """A request whose findings text the server builds from units + groups with the gate-less builder (spec §5
    Builder: /stack/draft and the Copilot routes). The string field stays accepted until P2c switches the browser;
    when units are sent they win."""
    units: list[StackUnit] | None = Field(default=None, max_length=400)
    groups: list[str] | None = None
    units_text_field: ClassVar[str] = "findings"

    @model_validator(mode="after")
    def _text_from_units(self):
        if self.units is not None:
            setattr(self, self.units_text_field, findings_text(self.units, self.groups or []))
        return self
