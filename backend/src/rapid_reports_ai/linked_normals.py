"""Linked normals: atoms to decide, prose to render (opt-in, RR_GROUPED_NORMALS).

With the analyser's grouped_normals directive the Normal-study path is written as two linked views:

    - N1 | liver | The liver is unremarkable.            one atom per structure / structure-specific negative
    - P1 | N1 N2 N3 | The liver, spleen and pancreas are unremarkable.   prose naming its atoms

The brief
  - labels every atom with the negatives classifier's judgement (dictated / default / implicated /
    contradicted), in the brief's reasoning-off Qwen call ("fold") or a separate reasoning-low call
    ("separate"), RR_LINKED_LABELLER;
  - checks every prose sentence against its atoms: code (each atom's exact term is in the sentence, no
    measurement) and Jev (D1 per atom: dropped if P(stated) < 0.80; A1 per sentence: added if P >= 0.30;
    review_labs/prose_atom). Jev unavailable -> the code check alone;
  - renders: default atoms grouped by subtraction from the prose; implicated atoms kept, each as its own
    short sentence; contradicted atoms "do not assert"; dictated atoms left to the dictation. A sentence
    that fails its link check renders as its atoms, one short line each.

    parse_linked   the field's lines -> Linked (units of prose + atoms, loose sentences) or None
    strip_links    the raw sheet with the linked field reduced to its prose (generator fallback path)
    code_check / link_questions / link_verdict   the prose <-> atom link check
    classifier prompts and label parsing
    render_unit    one prose unit -> rendered text, per-atom actions and spans

Pure code, no model calls.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, field_validator

from . import normal_groups as _ng

_MEASUREMENT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|°|(?:mm|cm|ml|mL|cc|HU|mmHg|m/s|degrees?)(?![A-Za-z]))")


def labeller() -> str:
    """RR_LINKED_LABELLER: "fold" (into the brief's reasoning-off Qwen call) or "separate" (reasoning low)."""
    v = os.environ.get("RR_LINKED_LABELLER", "fold").strip().lower()
    return v if v in ("fold", "separate") else "fold"


# ── parse ────────────────────────────────────────────────────────────────────

_LINE = re.compile(r"^\s*(?:[-*]\s+)?\**\s*([NP])(\d+)\s*\**\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$")
_HEAD = re.compile(r"^\s*-\s+\*\*Normal-study path:?\*\*:?\s*")


@dataclass
class Atom:
    id: str          # "N3"
    term: str        # the exact structure / finding term the prose must reuse
    text: str        # the atom's own short sentence

    @property
    def negative(self) -> bool:
        return bool(re.match(r"^\s*(?:no|there is no|there are no|without)\b", self.text, re.I))

    def phrase(self) -> str:
        """The atom as a clause for "It states that ...": "the liver is unremarkable", "there is no X"."""
        p = self.text.strip().rstrip(".").strip()
        if re.match(r"^no\b", p, re.I):
            return "there is " + p[0].lower() + p[1:]
        return p[0].lower() + p[1:] if p[:4] in ("The ", "Both") or p[:2] == "A " else p


@dataclass
class Unit:
    prose: Optional[str]           # None: an atom no prose line names (renders as itself)
    pid: Optional[str]
    atoms: List[Atom]
    problem: str = ""              # a parse problem: the link check fails


@dataclass
class Linked:
    entries: List[Union[Unit, str]] = field(default_factory=list)   # str: a loose sentence (per-line path)

    @property
    def units(self) -> List[Unit]:
        return [e for e in self.entries if isinstance(e, Unit)]

    @property
    def atoms(self) -> List[Atom]:
        return [a for u in self.units for a in u.atoms]


def _clean(s: str) -> str:
    return s.strip().strip('"').strip("“”").strip()


def _sentences(text: str) -> List[str]:
    text = _clean(text)
    return [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", text) if len(s.strip()) > 3]


def parse_linked(lines: List[str]) -> Optional[Linked]:
    """The Normal-study path bullet's lines as linked atoms and prose, or None when it holds no atom line
    (the caller then takes today's per-line path for the whole block). Lines in neither form are loose
    sentences, taken one by one on the per-line path; never dropped, never asserted unchecked."""
    atoms: Dict[str, Atom] = {}
    order: List[str] = []
    raw: List[Tuple[str, object]] = []        # ("P", (pid, ids, text)) | ("L", sentence)
    for i, line in enumerate(lines):
        body = _HEAD.sub("", line) if i == 0 else line
        if not body.strip():
            continue
        m = _LINE.match(body)
        if m and m.group(1) == "N":
            aid = f"N{int(m.group(2))}"
            if aid not in atoms and m.group(3).strip() and m.group(4).strip():
                atoms[aid] = Atom(aid, _clean(m.group(3)), _clean(m.group(4)))
                order.append(aid)
            continue
        if m and m.group(1) == "P":
            ids = [f"N{int(x)}" for x in re.findall(r"N\s*(\d+)", m.group(3))]
            raw.append(("P", (f"P{int(m.group(2))}", ids, _clean(m.group(4)))))
            continue
        for s in _sentences(re.sub(r"^\s*[-*]\s+", "", body)):
            raw.append(("L", s))
    if not atoms:
        return None
    used: set = set()
    entries: List[Union[Unit, str]] = []
    for kind, v in raw:
        if kind == "L":
            entries.append(v)
            continue
        pid, ids, text = v
        good = [i for i in ids if i in atoms and i not in used]
        problem = "" if (good and len(good) == len(ids)) else "unknown or repeated atom id"
        if not good:
            entries.append(text)   # prose naming no usable atom: a loose sentence
            continue
        used.update(good)
        entries.append(Unit(text, pid, [atoms[i] for i in good], problem))
    # An atom no prose names renders as itself, after the unit holding the atom before it.
    rank = {a: k for k, a in enumerate(order)}
    for aid in order:
        if aid in used:
            continue
        pos = 0
        for k, e in enumerate(entries):
            if isinstance(e, Unit) and any(rank[a.id] < rank[aid] for a in e.atoms):
                pos = k + 1
        entries.insert(pos, Unit(None, None, [atoms[aid]]))
        used.add(aid)
    return Linked(entries)


def strip_links(sheet: str) -> str:
    """The sheet with a linked Normal-study path reduced to its prose (P sentences, and atoms no prose
    names), as one quoted string. Used only when the brief fails and the generator reads the raw sheet."""
    m = re.search(r"^- \*\*Normal-study path:?\*\*:?.*?(?=^- \*\*|^## |\Z)", sheet, re.S | re.M)
    if not m:
        return sheet
    lk = parse_linked(m.group(0).rstrip("\n").split("\n"))
    if lk is None:
        return sheet
    parts = [e if isinstance(e, str) else (e.prose if e.prose else " ".join(a.text for a in e.atoms))
             for e in lk.entries]
    return sheet[:m.start()] + f'- **Normal-study path:** "{" ".join(parts)}"\n' + sheet[m.end():]


# ── link check ───────────────────────────────────────────────────────────────

D_STATED_MIN = 0.80     # D1: an atom with P(stated) below this is dropped from its sentence
A_ADDED_MIN = 0.30      # A1: a sentence with P(added) at or above this states something outside its atoms


def term_in(term: str, sentence: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", sentence, re.I))


def code_check(u: Unit) -> List[str]:
    """Reasons the prose cannot stand for its atoms, by code: no prose, a parse problem, a measurement, or
    an atom whose exact term the sentence does not contain (broadened, shortened or merged names)."""
    if not u.prose:
        return ["no prose"]
    out = [u.problem] if u.problem else []
    if _MEASUREMENT.search(u.prose):
        out.append("measurement")
    out += [f"term missing: {a.id} {a.term}" for a in u.atoms if not term_in(a.term, u.prose)]
    return out


def link_questions(u: Unit) -> dict:
    """One Jev request per sentence (the state is the sentence alone): D1 per atom, A1 for the sentence."""
    qs = {f"d{j}": {"type": "noul", "instructions": f"Read only this sentence. It states that {a.phrase()}.",
                    "criteria": {"true": "the sentence states it", "false": "the sentence does not state it"}}
          for j, a in enumerate(u.atoms)}
    qs["add"] = {"type": "noul",
                 "instructions": ("Read only this sentence. It states something about a structure or finding other "
                                  "than: " + "; ".join(a.phrase() for a in u.atoms) + "."),
                 "criteria": {"true": "it mentions another structure or finding", "false": "it mentions nothing else"}}
    return qs


def link_verdict(u: Unit, answers: Optional[dict]) -> dict:
    """{ok, code, dropped, added, jev}. answers None: Jev failed, the code check decides alone."""
    code = code_check(u)
    out = {"ok": not code, "code": code, "dropped": [], "added": None, "jev": "skipped" if code else "error"}
    if code or answers is None:
        return out
    try:
        stated = [float(answers[f"d{j}"]["noul"]) for j in range(len(u.atoms))]
        added = float(answers["add"]["noul"])
    except (KeyError, TypeError, ValueError):
        return out
    out["jev"] = "ok"
    out["dropped"] = [a.id for a, p in zip(u.atoms, stated) if p < D_STATED_MIN]
    out["added"] = round(added, 3)
    out["ok"] = not out["dropped"] and added < A_ADDED_MIN
    return out


# ── labels (the negatives classifier's judgement on the atoms) ───────────────

CLASSES = ("dictated", "default", "implicated", "contradicted")
_NEG_PROMPT = Path(__file__).parent / "review_engine" / "prompts" / "negatives.txt"


def _classifier_core() -> str:
    """The classifier's convention, process of exclusion, Step 1 and Step 2 (review_engine negatives.v5),
    verbatim; the report-specific opening and the number check are replaced."""
    t = _NEG_PROMPT.read_text()
    return t[t.index("The radiologist's convention"):t.index("Also report, for each statement")].strip()


SEPARATE_SYS = (
    "You read the normal and negative statements a report template will state for this study, beside the "
    "radiologist's dictation. The template was written from the scan type and clinical history before the "
    "dictation; a few statements may restate the dictation, most fill in what it does not mention. Classify each "
    "numbered statement.\n\n" + _classifier_core() + "\n\n"
    'Output one line per statement in `labels`, in order, exactly: "<n> | <class> | <the dictated words that point '
    'towards it, or ->".')

FOLD_SYS = (
    "\nNORMAL STATEMENTS: the normal and negative statements a report template will state for this study, written "
    "before the dictation. Classify each numbered statement as below. Write your Step 1 notes in normal_notes "
    "first (short), then one line per statement in normal_labels, in order, exactly: \"<n> | <class> | <the "
    "dictated words that point towards it, or ->\".\n\n" + _classifier_core())


def statements_block(atoms: List[Atom], clinical_history: str) -> str:
    listing = "\n".join(f"{i}. {a.text}" for i, a in enumerate(atoms, 1))
    return f"CLINICAL HISTORY:\n{clinical_history or '(none)'}\n\nNORMAL STATEMENTS TO CLASSIFY:\n{listing}"


def separate_user(scan_type: str, clinical_history: str, findings: str, atoms: List[Atom]) -> str:
    listing = "\n".join(f"{i}. {a.text}" for i, a in enumerate(atoms, 1))
    return (f"STUDY TITLE: {scan_type}\n\nCLINICAL HISTORY:\n{clinical_history or '(none)'}\n\nDICTATION:\n{findings}"
            f"\n\nSTATEMENTS TO CLASSIFY:\n{listing}")


def _decode_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if s.startswith("["):
        try:
            out = json.loads(s)
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            pass
    return [x for x in s.split("\n") if x.strip()]


class AtomLabels(BaseModel):     # flat on purpose (L-50)
    labels: List[str]

    @field_validator("labels", mode="before")
    @classmethod
    def _decode(cls, v):
        return [str(x) for x in _decode_list(v)]


def parse_labels(lines: List[str], n: int) -> Dict[int, dict]:
    """'<n> | <class> | <pointer or ->' -> {n (1-based): {cls, pointer}}; unknown classes and out-of-range dropped."""
    out = {}
    for line in lines or []:
        parts = [p.strip() for p in str(line).split("|")]
        if len(parts) < 2 or not parts[0].strip(". ").isdigit():
            continue
        i, cls = int(parts[0].strip(". ")), parts[1].lower()
        if 1 <= i <= n and cls in CLASSES and i not in out:
            out[i] = {"cls": cls, "pointer": parts[2] if len(parts) > 2 and parts[2] != "-" else ""}
    return out


# ── render ───────────────────────────────────────────────────────────────────

@dataclass
class UnitRender:
    mode: str                      # verbatim | subtracted | tail_only | atoms | none
    text: Optional[str]
    atoms: List[dict]              # per atom: id, term, text, label, action, own_line, span (in text)
    flagged: List[str]             # atom sentences for "do not assert"


def _span(text: str, needle: str, pos: int = 0) -> Optional[Tuple[int, int]]:
    m = re.compile(r"(?<![A-Za-z])" + re.escape(needle) + r"(?![A-Za-z])", re.I).search(text, pos)
    return (m.start(), m.end()) if m else None


def render_unit(u: Unit, labels: Dict[str, dict], link_ok: bool, dneg: List[str], positives: List[str]) -> UnitRender:
    """labels: atom id -> {"cls", "pointer", "source"}. default -> grouped by subtraction from the prose;
    implicated -> kept as its own sentence; contradicted -> do not assert; dictated -> left to the dictation.
    Guards (attempt 4): a default negative a dictated negative already says is left to the dictation; a
    default structure a dictated positive finding names gets its own sentence."""
    structures = [a.term for a in u.atoms if not a.negative]
    recs = []
    for a in u.atoms:
        lab = labels.get(a.id) or {"cls": "default", "pointer": "", "source": "none"}
        cls = lab["cls"]
        action, own, why = {"default": "keep", "implicated": "implicated", "contradicted": "do_not_assert",
                            "dictated": "dictated"}[cls], cls == "implicated", ""
        if cls == "default" and a.negative:
            told = _ng.covered_by_dictation(a.term, dneg, structures)
            if told:
                action, why = "dictated", f"dictated negative: {told}"
        if action == "keep" and not a.negative and _ng.dictated_overlap([a.term], positives):
            own, why = True, "named by a dictated finding"
        recs.append({"id": a.id, "term": a.term, "text": a.text, "label": cls, "label_source": lab.get("source", ""),
                     "pointer": lab.get("pointer", ""), "action": action, "own_line": own, "why": why, "span": None})
    grouped = [r["action"] == "keep" and not r["own_line"] for r in recs]
    parts: List[str] = []
    mode = "none"
    if any(grouped):
        if link_ok and u.prose and all(grouped):
            parts, mode = [u.prose], "verbatim"
        elif link_ok and u.prose:
            g = _ng.parse_grouped(u.prose)
            names = (g.structures + g.tail) if g else []
            terms = {a.term.lower(): k for k, a in enumerate(u.atoms)}
            idx = [terms.get(n.lower()) for n in names]
            if g and None not in idx and sorted(idx) == list(range(len(u.atoms))):
                r = _ng.subtract(g, [grouped[k] for k in idx])
                if r.mode in ("subtracted", "tail_only", "verbatim") and r.text:
                    parts, mode = [r.text], r.mode
        if not parts:
            parts, mode = [a.text for a, k in zip(u.atoms, grouped) if k], "atoms"
    head = " ".join(parts)
    own_parts = [a.text for a, r in zip(u.atoms, recs) if r["own_line"] and r["action"] in ("keep", "implicated")]
    text = " ".join(x for x in [head] + own_parts if x) or None
    # Spans: a grouped atom's term inside the grouped text; an own-line atom's whole sentence.
    pos = 0
    for a, r, k in zip(u.atoms, recs, grouped):
        if k and text:
            sp = _span(head, a.term if mode in ("verbatim", "subtracted", "tail_only") else a.text, pos)
            if sp:
                r["span"] = list(sp)
                pos = sp[1]
    pos = len(head) + (1 if head else 0)
    for a, r in zip(u.atoms, recs):
        if r["own_line"] and r["action"] in ("keep", "implicated") and text:
            s = text.find(a.text, pos)
            if s >= 0:
                r["span"] = [s, s + len(a.text)]
                pos = s + len(a.text)
    flagged = [a.text for a, r in zip(u.atoms, recs) if r["action"] == "do_not_assert"]
    return UnitRender(mode if text else "none", text, recs, flagged)
