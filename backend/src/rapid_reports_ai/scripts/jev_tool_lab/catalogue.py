"""Question catalogue (spec 2026-10-02-qwen-authored-jev-questions-lab-design §2).

Qwen picks a question type and fills its slots; the wording is owned here, by code, and comes from measured Jev
results (memory reference_jev_capability_profile, ledger L-46/L-49). validate() rejects a slot set that drifts into
a type Jev is weak at."""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from rapid_reports_ai.report_review import Q_CONTRA

Source = Literal["dictation", "report", "history"]
QType = Literal["T1", "T2", "T3", "T4", "T5", "T6"]

SOURCE_NAME = {"dictation": "dictated findings", "report": "report", "history": "clinical history"}
SUBJECT = {"dictation": "The dictated findings themselves state",
           "report": "The report itself states",
           "history": "The clinical history itself states"}
CANT_TELL = "cant_tell"
MAX_QUESTIONS = 8
MAX_TOPIC_WORDS = 8   # 6 rejected topics that name their finding (smoke, 2026-10-02); Jev wording checked to 6
MAX_OPTION_WORDS = 25
# T5 starts with its one proven property (group F selector noul, AUC ~1.0); more join only after a mini-check.
PROPERTIES = {"abnormal": "reports an abnormality or a limitation, including as a possibility"}
_NEGATION = {"no", "not", "without", "absent", "negative", "normal", "unremarkable", "nil", "none", "non"}
_AUX = {"do", "does", "did", "is", "are", "was", "were", "has", "have"}   # "X enhance" vs "X do not enhance"
_WORD = re.compile(r"[a-z0-9']+")

# The two new wordings (spec §5 phase 1). The mini-check picks w1 or w2 and records it in DEFAULT_WORDING.
WORDINGS: Dict[str, Dict[str, dict]] = {
    "T2d": {
        "w1": {"instructions": "The dictated findings themselves say something about this topic, whatever they say "
                               "about it (present, absent, normal, a measurement or a description): {topic}",
               "criteria": {"true": "The dictation mentions this topic, in any wording, abbreviation or synonym, "
                                    "whatever it says about it.",
                            "false": "The dictation says nothing about this topic."}},
        "w2": {"instructions": "Do the dictated findings say anything about {topic}, in any wording?",
               "criteria": {"true": "Yes: the dictation describes {topic} in some way (present, absent, normal, "
                                    "measured or described), in any wording or synonym.",
                            "false": "No: {topic} is not mentioned anywhere in the dictation."}},
    },
    "T6": {
        "w1": {"instructions": '"{a}" and "{b}" describe the same structure or finding.',
               "criteria": {"true": "Both refer to the same structure or finding, in any wording.",
                            "false": "They refer to different structures or findings, or to a different side or "
                                     "level."}},
        "w2": {"instructions": 'Read only these two quoted texts: "{a}" and "{b}". They are about the same structure '
                               'or finding, at the same side and level.',
               "criteria": {"true": "Same structure or finding, same side and level, in any wording.",
                            "false": "A different structure or finding, or a different side or level."}},
    },
}
DEFAULT_WORDING = {"T2d": "w1", "T6": "w2"}   # phase 1 mini-check, 2026-10-02 (spec Results)


class Case(BaseModel):
    scan_type: str = ""
    dictation: str
    report: str = ""
    history: str = ""

    def text(self, source: str) -> str:
        return {"dictation": self.dictation, "report": self.report, "history": self.history}[source]


class QuestionSpec(BaseModel):
    """One question as Qwen fills it: a type plus slots. Flat on purpose (one nesting level for Qwen's output)."""
    id: str
    type: QType
    source: Optional[Source] = None
    section: Optional[str] = None
    item: Optional[str] = None
    topic: Optional[str] = None
    clause: Optional[str] = None
    options: Optional[List[str]] = None
    property: Optional[str] = None
    a: Optional[str] = None
    b: Optional[str] = None


def state_for(case: Case, source: str) -> str:
    if source == "dictation":
        return f"SCAN TYPE: {case.scan_type}\nDICTATED FINDINGS:\n{case.dictation}"
    if source == "report":
        return f"REPORT:\n{case.report}"
    return f"CLINICAL HISTORY:\n{case.history}"


def question_source(spec: QuestionSpec) -> str:
    """The text Jev reads as state for this question."""
    if spec.type == "T3":
        return "dictation"
    return spec.source or "dictation"


def _norm(t: str) -> str:
    return " ".join(t.split()).casefold()


def _words(t: str) -> List[str]:
    return _WORD.findall(t.casefold())


def _quoted_in(quote: Optional[str], *texts: str) -> bool:
    """Whole-word sequence match, so "renal lesion" is not found inside "adrenal lesion"."""
    q = " ".join(_words(quote or ""))
    return bool(q) and any(f" {q} " in f" {' '.join(_words(t))} " for t in texts if t)


def _negation_pair(x: str, y: str) -> bool:
    wx, wy = _words(x), _words(y)
    rest = lambda ws: [w for w in ws if w not in _NEGATION and w not in _AUX]  # noqa: E731
    same_rest = rest(wx) == rest(wy)
    return same_rest and (set(wx) & _NEGATION) != (set(wy) & _NEGATION)


def validate(spec: QuestionSpec, case: Case) -> Optional[str]:
    """None when the slot set is a valid catalogue question for this case, else the reason it is rejected."""
    t = spec.type
    texts = (case.dictation, case.report, case.history)
    if t in ("T1", "T2", "T4") and spec.source is None:
        return "missing source"
    if t == "T2" and spec.source not in ("dictation", "report"):
        return "T2 source must be dictation or report"
    if not case.text(question_source(spec)).strip():
        return "source text is empty"
    if t == "T1":
        if not _quoted_in(spec.item, *texts):
            return "item not verbatim"
    elif t == "T2":
        if spec.source == "report" and not spec.section:
            return "T2 on the report needs a section"
        topic = (spec.topic or "").strip()
        words = _words(topic)
        if set(words) & _NEGATION:
            return "topic carries a negation"
        if any(ch.isdigit() for ch in topic):
            return "topic carries a number"
        if not 1 <= len(words) <= MAX_TOPIC_WORDS:
            return f"topic must be 1-{MAX_TOPIC_WORDS} words"
    elif t == "T3":
        if not _quoted_in(spec.clause, case.report):
            return "clause not verbatim in the report"
    elif t == "T4":
        if not _quoted_in(spec.item, *texts):
            return "item not verbatim"
        opts = spec.options or []
        if not 2 <= len(opts) <= 5:
            return "T4 needs 2-5 options"
        if any(not o.strip() or len(_words(o)) > MAX_OPTION_WORDS for o in opts):
            return "option too long or empty"
        if len({_norm(o) for o in opts}) < len(opts):
            return "duplicate options"
        if any(_negation_pair(x, y) for i, x in enumerate(opts) for y in opts[i + 1:]):
            return "an option negates another"
    elif t == "T5":
        if not _quoted_in(spec.item, *texts):
            return "item not verbatim"
        if spec.property not in PROPERTIES:
            return "unknown property"
    elif t == "T6":
        if not (_quoted_in(spec.a, *texts) and _quoted_in(spec.b, *texts)):
            return "span not verbatim"
        if _norm(spec.a) == _norm(spec.b):
            return "a and b are the same text"
    return None


def _from_wording(kind: str, wording: Optional[str], **slots) -> dict:
    w = WORDINGS[kind][wording or DEFAULT_WORDING[kind]]
    return {"type": "noul", "instructions": w["instructions"].format(**slots),
            "criteria": {k: v.format(**slots) for k, v in w["criteria"].items()}}


def render(spec: QuestionSpec, wording: Optional[str] = None) -> dict:
    """The Jev question JSON for a validated spec. `wording` overrides DEFAULT_WORDING for T2-dictation and T6."""
    t = spec.type
    if t == "T1":
        return {"type": "noul",
                "instructions": f'Read only this one quoted text: "{spec.item}". {SUBJECT[spec.source]} what it says, '
                                "in any wording, abbreviation or synonym, or spread over more than one sentence, "
                                "including as a possibility (not merely implied or inferable).",
                "criteria": {"true": "It is stated there, in any wording (synonym, abbreviation or a more specific "
                                     "form), as present or possible.",
                             "false": "It is not mentioned there, is stated as absent or normal, or only something "
                                      "different that shares some words with it is stated."}}
    if t == "T2":
        if spec.source == "report":
            return {"type": "noul",
                    "instructions": f"Does the {spec.section} section of the report say whether there is {spec.topic}?"}
        return _from_wording("T2d", wording, topic=spec.topic)
    if t == "T3":
        return {"type": "noul", "instructions": Q_CONTRA + spec.clause}
    if t == "T4":
        name = SOURCE_NAME[spec.source]
        criteria = {f"o{i + 1}": o for i, o in enumerate(spec.options)}
        criteria[CANT_TELL] = "It is not possible to tell from this text which description fits."
        return {"type": "choice",
                "instructions": f'Read only this one quoted text: "{spec.item}". Using only the {name}, choose the '
                                "description that fits it.",
                "criteria": criteria}
    if t == "T5":
        return {"type": "noul", "instructions": f'The quoted text "{spec.item}" itself {PROPERTIES[spec.property]}.'}
    return _from_wording("T6", wording, a=spec.a, b=spec.b)
