"""Plain-code baselines for the three dictation bake-offs. No model, no network.

Every bake-off reports one of these next to the model (rev 2 §5). They were drafted
after the fixtures existed, so their scores are an optimistic ceiling for a lexicon
approach. Lexicon entries are generic dictation cues only, never fixture phrases;
do not tune them to a bake-off result.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

DELETE_PATTERNS = (
    r"\b(scratch|scrap|strike|delete|remove|ignore) (that|the last (line|one|sentence))\b",
    r"\bundo that\b",
)
FORMAT_PATTERNS = (
    r"^(new|next) (line|paragraph)( please)?$",
    r"^paragraph$",
    r"^(full stop|comma|period)$",
    r"^new heading\b",
)
APP_COMMAND_PATTERNS = (r"^generate (the )?report$", r"^switch to \w+ mode$")
CORRECTION_PATTERNS = (
    r"^actually\b", r"\bmake that\b", r"^sorry\b", r"\bi mean\b", r"^correction\b",
    r"^change .+ to\b", r"\bits not .+ its\b", r"^\w+ not \w+$",
)
FILLERS = frozenset(
    "um umm er erm uh ah hmm so well okay ok right yeah yes let me see just hang on a second wait "
    "testing".split()
)
# A statement that stops on one of these is waiting for more words.
TRAILING_OPEN = frozenset(
    "the a an of in on at to from with without and or but which that is are was were there "
    "measuring actually make".split()
)
STOP = frozenset("the a an of in on at to with and or is are was there it this that no so as i said".split())

# Adjectival and abbreviated forms a checklist section is commonly written in.
SECTION_FORMS: dict[str, tuple[str, ...]] = {
    "LIVER": ("liver", "hepatic"),
    "KIDNEYS": ("kidney", "kidneys", "renal"),
    "LUNGS": ("lung", "lungs", "lobe", "pulmonary"),
    "PLEURA": ("pleura", "pleural"),
    "MEDIASTINUM": ("mediastinum", "mediastinal"),
    "HEART": ("heart", "cardiac"),
    "COMMON BILE DUCT": ("common bile duct", "cbd"),
    "INTERVERTEBRAL DISCS": ("disc", "discs"),
    "SPINAL CANAL": ("canal",),
}


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower().replace("'", "")))


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _content(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in STOP}


def is_command(text: str) -> bool:
    t = _norm(text)
    return _any(DELETE_PATTERNS, t) or _any(FORMAT_PATTERNS, t) or _any(APP_COMMAND_PATTERNS, t)


def baseline_triage(committed: str, active: str, utterance: str) -> str:
    t = _norm(utterance)
    if _any(DELETE_PATTERNS, t):
        return "delete_previous_utterance"
    if _any(FORMAT_PATTERNS, t):
        return "formatting_command"
    if _any(CORRECTION_PATTERNS, t):
        return "correct_previous_finding"
    if not any(ch.isdigit() for ch in t) and all(w in FILLERS for w in t.split()):
        return "ignore_noise"
    content = _content(utterance)
    seen = _content(committed) | _content(active)
    if content and len(content & seen) / len(content) >= 0.6:
        return "restate_existing_finding"
    return "append_new_finding"


def baseline_boundary(buffered: str, chunk: str) -> str:
    if is_command(chunk):
        return "command"
    words = _norm(f"{buffered} {chunk}").split()
    if len(words) < 3 or words[-1] in TRAILING_OPEN:
        return "continues"
    return "complete"


def baseline_coverage(scratchpad: str, sections: list[str]) -> dict[str, float]:
    """1.0 when a section's name or a listed form appears in a line that asserts more
    than the bare name; 0.0 otherwise. No collectives: that is what the model adds."""
    lines = [_norm(l.lstrip("-* ")) for l in (scratchpad or "").splitlines() if l.strip()]
    out: dict[str, float] = {}
    for s in sections:
        forms = SECTION_FORMS.get(s.upper(), (s.lower(),))
        hit = any(re.search(rf"\b{re.escape(f)}\b", line) and line != f for line in lines for f in forms)
        out[s] = 1.0 if hit else 0.0
    return out
