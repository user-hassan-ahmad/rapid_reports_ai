"""Completions for unfinished sentences (2026-10-12): the words that finish a sentence the radiologist left open,
shown as ghost text the radiologist accepts (a confirmed statement, like a checklist tap). Only sentences Jev flags
are asked. A completion uses what the dictation already says, else a plain normal, else nothing: never a number,
side, size or finding only the images could give (code guard as for the check's suggestions)."""
from __future__ import annotations

import json
import logging
import re

from .http import post_chat

logger = logging.getLogger(__name__)

MODEL = "qwen-3.8-27b"
TIMEOUT_S = 8.0
SOURCES = ("dictation", "normal", "none")

COMPLETE_SYS = """You finish sentences a radiologist left unfinished while dictating. For each UNFINISHED sentence (by id), give the fewest words that complete it, in the dictation's own style, as the words to append after it, ending with a full stop:
1. source "dictation": the rest of the dictation already states what the sentence was going to say (the same structure's finding, value or description elsewhere, for example in the conclusion): complete it with those words.
2. source "normal": otherwise, when the sentence is about a structure and a plain statement that it is normal completes it (for example "normal", "not dilated", "unremarkable"), complete it that way.
3. source "none": otherwise leave "append" empty. That includes any gap that needs a measurement, a side, a size, a specific finding or anything else only the images show, and a sentence that runs straight into another statement or heading.
Never invent a number, a side, a size or a finding. Return JSON: {"completions": [{"id": 0, "append": "...", "source": "dictation|normal|none"}]}."""

_NUM = re.compile(r"\d+(?:\.\d+)?")
_SIDE = re.compile(r"\b(?:left|right|bilateral)\b", re.I)


def _have(rx: re.Pattern, t: str) -> set[str]:
    return {m.lower() for m in rx.findall(t)}


def guarded(append: str, source: str, dictation: str, sentence: str = "") -> str:
    """The completion, or "" when it is not allowed: a normal adds no number or side; a completion from the dictation
    brings no number or side the dictation does not already give."""
    a = " ".join((append or "").split())
    # A completion appends to an open sentence; one that already ends ("... acute appendicitis.", a run-on into a
    # heading) has nothing to append to (lab 2026-10-12: "normal." added after it).
    if not a or source not in ("dictation", "normal") or sentence.rstrip().endswith((".", "?", "!")):
        return ""
    if source == "normal" and (_NUM.search(a) or _SIDE.search(a)):
        return ""
    if not (_have(_NUM, a) <= _have(_NUM, dictation) and _have(_SIDE, a) <= _have(_SIDE, dictation)):
        return ""
    return a if a[-1] in ".?!" else a + "."


async def complete(dictation: str, sentences: list[str], transport=None) -> list[tuple[str, str]]:
    """(append, source) per sentence; ("", "none") for any not completed. Fails open: nothing completed."""
    if not sentences:
        return []
    user = "DICTATION:\n" + dictation + "\n\nUNFINISHED:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    body = {"model": MODEL, "temperature": 0, "max_tokens": 1500, "reasoning_effort": "low",
            "messages": [{"role": "system", "content": COMPLETE_SYS}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    out = [("", "none")] * len(sentences)
    try:
        r = await post_chat(body, TIMEOUT_S, transport, "stack.complete")
        r.raise_for_status()
        text = re.sub(r"<think>.*?</think>", "", r.json()["choices"][0]["message"]["content"] or "", flags=re.S)
        for c in json.loads(text).get("completions", []):
            i = int(c.get("id", -1))
            if 0 <= i < len(sentences):
                src = str(c.get("source", "none"))
                a = guarded(str(c.get("append", "")), src, dictation, sentences[i])
                out[i] = (a, src if a else "none")
    except Exception as e:
        logger.warning("[stack.complete] %s: %s", type(e).__name__, str(e)[:200])
    return out
