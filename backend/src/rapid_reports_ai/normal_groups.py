"""Grouped normal sentences: split to decide, subtract to render (opt-in, RR_GROUPED_NORMALS).

With the analyser's grouped_normals directive the Normal-study path is written as consultant
group sentences ("The A, B and C are unremarkable." / "The D is unremarkable with no X or Y.").
The brief verifies each structure and each tail negative on its own, then renders the sentence
as the original minus its affected parts, so the generator copies fluent grouped wording rather
than an inventory, and no wording is composed beyond list joins and is/are agreement.

    parse_grouped   sentence -> lead, structures, verb, descriptor, tail negatives (or None)
    atoms           one stated line per structure / tail negative, for Jev and Qwen
    subtract        the sentence minus the affected atoms, self-checked by re-parsing
    per_structure   fallback: one line per kept atom
    dictated_overlap  a kept atom shares a content word with something dictated

Pure code, no model calls.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


def enabled() -> bool:
    """RR_GROUPED_NORMALS=1 turns on the analyser directive and the grouped brief (default off)."""
    return os.environ.get("RR_GROUPED_NORMALS", "0").strip().lower() in ("1", "true", "on")


_VERBS = {"is": "are", "are": "are", "appears": "appear", "appear": "appear", "remains": "remain", "remain": "remain"}
_SINGULAR = {"are": "is", "appear": "appears", "remain": "remains"}
_SENT = re.compile(
    r"^(?P<lead>(?:The|Both)\s+)?(?P<subj>.+?)\s+(?P<verb>is|are|appears?|remains?)\s+(?P<desc>.+?)"
    r"(?:(?P<intro>,?\s+with\s+no\s+|,?\s+without\s+|;\s*no\s+|,\s*no\s+|,?\s+and\s+no\s+)(?P<tail>.+?))?\.?$")
_SUBJ_SEP = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+")
_TAIL_SEP = re.compile(r"\s*,\s*(?:(?:or|and|nor)\s+)?(?:no\s+)?|\s+(?:or|nor)\s+|\s+and\s+no\s+")
_BAD_ITEM = re.compile(r"\d|[():;\"]|\b(?:no|not|with|without|which|that|is|are|but|apart|except|otherwise|its|their|including)\b", re.I)
_BAD_DESC = re.compile(r"\d|[,;:()\"]|\b(?:no|with|without|but|apart|except|otherwise|which)\b", re.I)
_PLURAL_WORDS = {"viscera", "adnexa", "adnexae", "vertebrae", "bronchi", "data", "ganglia", "thalami", "sulci",
                 "gyri", "foramina", "cornua", "labia", "meninges"}
_SINGULAR_WORDS = {"pons", "lens", "series", "mons"}


_MODIFIERS = {"left", "right", "upper", "lower", "deep", "superficial", "internal", "external", "central",
              "peripheral", "small", "large", "intra", "extra", "both", "median", "flexor", "extensor", "common",
              "main", "greater", "lesser", "major", "minor"}
_NOT_MODIFIERS = {"canal", "signal", "interval", "pillar", "collar"}


def _is_modifier(item: str) -> bool:
    """A list item ending in an adjective, sharing the next item's head noun ("dorsal and volar soft
    tissues", "lower thoracic and lumbar spine")."""
    w = item.lower().split()[-1]
    return w not in _NOT_MODIFIERS and (w in _MODIFIERS or bool(re.search(r"(?:al|ar|ic|ior|ous)$", w)))


# A bare part noun after a named structure borrows its owner ("femoral head, neck and ...").
_PART_NOUNS = {"head", "neck", "body", "tail", "base", "shaft", "root", "wall", "apex", "dome", "fundus", "hook",
               "waist", "tip", "roof", "floor"}


def is_plural(structure: str) -> bool:
    w = re.findall(r"[a-z]+", structure.lower().split(" of ")[0])[-1:] or [""]
    w = w[0]
    if w in _PLURAL_WORDS:
        return True
    if w in _SINGULAR_WORDS:
        return False
    return w.endswith("s") and not w.endswith(("ss", "us", "is", "as"))


@dataclass
class Grouped:
    text: str
    lead: str                 # "The " / "Both " / ""
    structures: List[str]
    verb: str                 # as written
    descriptor: str
    intro: str                # " with no " etc., "" without a tail
    tail: List[str]
    tail_conj: str = "or"     # "or" | "and" | "and no"
    oxford: bool = False

    def structure_line(self, s: str) -> str:
        lead = self.lead if len(self.structures) == 1 else "The "
        return f"{lead}{s} {verb_for([s], self.verb)} {self.descriptor}."

    def atoms(self) -> List[Tuple[str, str]]:
        """(kind, stated line) per structure then per tail negative."""
        return ([("structure", self.structure_line(s)) for s in self.structures]
                + [("tail", f"No {t}.") for t in self.tail])


def verb_for(structures: List[str], verb: str) -> str:
    plural = _VERBS.get(verb, verb)
    if len(structures) > 1 or is_plural(structures[0]):
        return plural
    return _SINGULAR.get(plural, verb)


def parse_grouped(sentence: str) -> Optional[Grouped]:
    """The sentence as a structure list with a bare descriptor and optional tail negatives, or None."""
    s = sentence.strip()
    m = _SENT.match(s)
    if not m:
        return None
    subj, desc = m.group("subj"), m.group("desc")
    raw_items = _SUBJ_SEP.split(subj)
    raw_seps = [x.group() for x in _SUBJ_SEP.finditer(subj)]
    # An item ending in an adjective shares the next item's head noun ("dorsal and volar soft tissues",
    # "lower thoracic and lumbar spine"): it joins that item, as written, to make one structure.
    structures, seps, cur = [], [], raw_items[0]
    for sep, nxt in zip(raw_seps, raw_items[1:]):
        if cur.strip() and _is_modifier(cur):
            if len(nxt.split()) < 2 and not _is_modifier(nxt):
                return None   # "gluteal, adductor, ...": no head noun closes the chain
            cur = cur + sep + nxt
        else:
            structures.append(cur.strip()); seps.append(sep); cur = nxt
    structures.append(cur.strip())
    if not all(structures) or any(_BAD_ITEM.search(p) for p in structures) or _BAD_DESC.search(desc):
        return None
    if _is_modifier(structures[-1]):
        return None
    if any(p.lower() in _PART_NOUNS for p in structures[1:]):
        return None   # "femoral head, neck and ...": the bare part borrows the previous item's owner
    if subj[:1].isupper() and not m.group("lead") and len(structures) > 1:
        return None   # "Visualised A and B": an unled subject is left alone
    tail, conj = [], "or"
    if m.group("tail"):
        raw = m.group("tail")
        tail = [p.strip() for p in _TAIL_SEP.split(raw)]
        if not all(tail) or any(_BAD_ITEM.search(p) for p in tail):
            return None
        seps = " ".join(x.group() for x in _TAIL_SEP.finditer(raw))
        conj = "and no" if re.search(r"\band\s+no\b", seps) else ("or" if re.search(r"\b(?:or|nor)\b", seps) or not seps
                                                                  else "and")
    oxford = bool(seps) and bool(re.match(r"\s*,\s*and\s", seps[-1]))
    return Grouped(s, m.group("lead") or "", structures, m.group("verb"), desc, m.group("intro") or "", tail,
                   conj, oxford)


def _join(items: List[str], conj: str, oxford: bool = False) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conj} {items[1]}"
    return ", ".join(items[:-1]) + ("," if oxford else "") + f" {conj} " + items[-1]


_ALLOWED_NEW = {"is", "are", "appears", "appear", "remains", "remain", "no", "the"}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", s.lower()))


@dataclass
class Render:
    mode: str                      # verbatim | subtracted | tail_only | per_structure | none
    text: Optional[str]            # None: nothing kept
    spans: List[Optional[Tuple[int, int]]] = field(default_factory=list)   # per atom, in `text`


def _spans(text: str, g: Grouped, keep: List[bool]) -> List[Optional[Tuple[int, int]]]:
    names = g.structures + g.tail
    out, pos = [], 0
    for name, k in zip(names, keep):
        if not k:
            out.append(None)
            continue
        m = re.compile(r"\b" + re.escape(name) + r"\b", re.I).search(text, pos)
        if m:
            out.append((m.start(), m.end()))
            pos = m.end()
        else:
            out.append(None)
    return out


def per_structure(g: Grouped, keep: List[bool]) -> Render:
    """One line per kept atom (the fallback, and the dictated-overlap render)."""
    lines = [line for (kind, line), k in zip(g.atoms(), keep) if k]
    if not lines:
        return Render("none", None, [None] * len(keep))
    text = " ".join(lines)
    return Render("per_structure", text, _spans(text, g, keep))


def subtract(g: Grouped, keep: List[bool]) -> Render:
    """The sentence minus its affected atoms. keep: per structure, then per tail negative.
    Self-check: the rebuilt sentence re-parses to exactly the kept structures, descriptor and kept
    tail, and holds no word the original lacks (bar is/are agreement); else per_structure."""
    ns = len(g.structures)
    ks = [s for s, k in zip(g.structures, keep[:ns]) if k]
    kt = [t for t, k in zip(g.tail, keep[ns:]) if k]
    if not ks and not kt:
        return Render("none", None, [None] * len(keep))
    if all(keep):
        return Render("verbatim", g.text, _spans(g.text, g, keep))
    if not ks:
        text = "No " + _join(kt, g.tail_conj) + "."
        ok = _words(text) <= _words(g.text) | _ALLOWED_NEW
        return Render("tail_only", text, _spans(text, g, keep)) if ok else per_structure(g, keep)
    lead = g.lead if g.lead.strip() != "Both" or len(ks) == 1 else "The "
    subj = _join(ks, "and", g.oxford)
    if not lead and ks[0] != g.structures[0]:
        subj = subj[:1].upper() + subj[1:]
    text = f"{lead}{subj} {verb_for(ks, g.verb)} {g.descriptor}"
    if kt:
        text += g.intro + _join(kt, g.tail_conj)
    text += "."
    back = parse_grouped(text)
    ok = (back is not None and back.structures == ks and back.tail == kt and back.descriptor == g.descriptor
          and _words(text) <= _words(g.text) | _ALLOWED_NEW)
    if not ok:
        return per_structure(g, keep)
    return Render("subtracted", text, _spans(text, g, keep))


# ── dictated overlap ────────────────────────────────────────────────────────

_GENERIC = {"the", "a", "an", "of", "in", "at", "on", "to", "and", "or", "no", "not", "with", "without", "is", "are",
            "both", "left", "right", "bilateral", "visualised", "visualized", "imaged", "major", "small", "large",
            "normal", "unremarkable", "focal", "lesion", "lesions", "abnormality", "significant", "evidence", "acute",
            "structures", "structure", "soft", "tissue", "tissues", "wall", "free", "remaining", "other", "any"}


def _stems(text: str) -> set:
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in _GENERIC or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 and not w.endswith("ss") else w)
    return out


_DICTATED_NORMAL = re.compile(r"\b(?:normal|unremarkable|intact|preserved|clear|patent|fine|satisfactory)\b", re.I)
_NEGATED = re.compile(r"^\s*(?:no|not|nil|without)\b", re.I)


def positive_findings(items: List[str]) -> List[str]:
    """Dictated items that report something: not a negative, not a normal statement ("tendons normal",
    "bones look fine"). A dictated normal cannot be displaced by a grouped sentence saying the same."""
    return [i for i in items if not _NEGATED.search(i) and not _DICTATED_NORMAL.search(i)]


def covered_by_dictation(tail_item: str, negatives: List[str]) -> Optional[str]:
    """The dictated negative that already says this tail negative (every content word of the tail
    item is in it), or None. Such a tail is left to the dictation: kept in the grouped sentence it
    reads as covering the dictated negative, and the generator drops the dictated one (8215140f)."""
    st = _stems(tail_item)
    return next((n for n in negatives if st and st <= _stems(n)), None)


def dictated_overlap(atom_texts: List[str], dictated: List[str]) -> List[str]:
    """The dictated items that share a content word with any of the atoms."""
    want = set().union(*(_stems(a) for a in atom_texts)) if atom_texts else set()
    return [d for d in dictated if _stems(d) & want]
