"""Jev gates of the targeted fetch (spec §2.20, §5.3, §5.5): judgements about meaning over source text. Jev judges
every evidence claim; code can only remove a claim (score below EVIDENCE_MIN), never approve one by exact match
alone (exact_signals is a logged signal, not a shortcut) — a verbatim quote can belong to the wrong branch,
edition or guideline. Other thresholds (COVER_MIN, ANSWERS_MIN) remain provisional until the seed lab (plan
Task 13) sets them where false yes answers reach zero."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from ...jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)

TIMEOUT_S = 6.0
STATE_MAX = 12000          # chars of source text per Jev call; the lab (Task 13) may raise this
WINDOW_CAP = 6             # a source past this many windows is capped, not sent whole (latency, cost)
SOURCE_MAX = STATE_MAX * WINDOW_CAP   # the structure step (Task 5) should cap a guideline's stored source to this

COVER_MIN = 0.7            # provisional: SOURCE states the criteria or management for a branch
# lab 2026-10-12 (24 claims x 2 runs, strict wording): true min 0.73, false max 0.19 (wrong-branch <=0.08);
# re-check on the Task 12 seed fixture
EVIDENCE_MIN = 0.5         # every evidence claim is judged by Jev; the exact-match fast path is a logged signal only
ANSWERS_MIN = 0.7          # provisional: the stored material answers a radiologist's question
RELEVANT_MIN = 0.5         # provisional: a search result is about the guideline asked for; the seed lab calibrates it
SNIPPET_MAX = 600          # chars of each search result's snippet shown to the relevance gate

_DASH = str.maketrans({"–": "-", "—": "-", "‐": "-", "−": "-"})
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _flat(s: str) -> str:
    s = s.lower().translate(_DASH).replace("≥", ">=").replace("≤", "<=")
    s = re.sub(r"[^\w<>=.%/+-]+|_", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    s = re.sub(r"(\d)\s*(mm|cm|%)\b", r"\1 \2", s)
    s = re.sub(r"([<>]=?)\s+", r"\1", s)
    return " ".join(s.split())


def quote_in(source: str, quote: str) -> bool:
    """The exact-match first pass: the quote appears in the source as whole tokens once whitespace, case,
    dashes and punctuation runs are flattened (tables lose their layout in extraction; meaning-level matches go to
    Jev). A quote under 4 tokens is too easy to false-match on a bare number or unit, so it never passes here."""
    q = _flat(quote)
    return len(q.split()) >= 4 and f" {q} " in f" {_flat(source)} "


def _numbers_covered(claim: str, quote: str) -> bool:
    """An exact quote only counts as evidence for a claim when every number the claim states also appears in the
    quote — otherwise "CT at 3 months" would pass evidence from a quote that actually says 6 months."""
    return set(_NUM.findall(claim)) <= set(_NUM.findall(quote))


def _windows(source: str) -> list[str]:
    """Split the source into windows that each fit STATE_MAX, breaking on chunk boundaries ("\\n\\n[", how fetch
    joins "[url]\\ntext" chunks) so a window never cuts mid-chunk; falls back to a plain paragraph split when the
    source carries no such markers. Capped at WINDOW_CAP windows (logged) rather than sent whole."""
    pieces = re.split(r"\n\n(?=\[)", source) if "\n\n[" in source else source.split("\n\n")
    windows: list[str] = []
    cur = ""
    for piece in pieces:
        nxt = f"{cur}\n\n{piece}" if cur else piece
        if cur and len(nxt) > STATE_MAX:
            windows.append(cur)
            cur = piece
        else:
            cur = nxt
    if cur:
        windows.append(cur)
    out: list[str] = []
    for w in windows:
        while len(w) > STATE_MAX:
            out.append(w[:STATE_MAX])
            w = w[STATE_MAX:]
        out.append(w)
    out = out or [""]
    if len(out) > WINDOW_CAP:
        logger.warning("[copilot.jev] %d windows, dropping %d beyond the cap of %d", len(out), len(out) - WINDOW_CAP, WINDOW_CAP)
        out = out[:WINDOW_CAP]
    return out


def _state(window: str) -> str:
    return "SOURCE:\n" + window


def scores(body: Any, keys) -> dict[str, float]:
    """The noul score per asked key from a Jev response body. A malformed or missing answer is an outage, never a low
    score: no `answers`, a missing key or a non-numeric `noul` raises ValueError into the caller's failure path."""
    ans = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(ans, dict):
        raise ValueError("jev response has no answers")
    out: dict[str, float] = {}
    for k in keys:
        a = ans.get(k)
        v = a.get("noul") if isinstance(a, dict) else None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            raise ValueError(f"jev answer {k!r} has no numeric noul")
        out[k] = float(v)
    return out


def choice(body: Any, key: str) -> tuple[str, float]:
    """(choice, confidence) for one choice question; malformed raises ValueError (an outage, never "none")."""
    ans = body.get("answers") if isinstance(body, dict) else None
    a = ans.get(key) if isinstance(ans, dict) else None
    c = a.get("choice") if isinstance(a, dict) else None
    conf = a.get("confidence") if isinstance(a, dict) else None
    if not isinstance(c, str) or isinstance(conf, bool) or not isinstance(conf, (int, float)) or conf != conf:
        raise ValueError(f"jev answer {key!r} has no choice/confidence")
    return c, float(conf)


async def _ask_once(state: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    return scores(r.json(), questions)


async def _ask(state: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    """One Jev call, retried once on any failure (timeout, HTTP error, malformed answer) before raising."""
    try:
        return await _ask_once(state, questions, transport)
    except Exception as e:
        logger.info("[copilot.jev] retrying once after %s: %s", type(e).__name__, str(e)[:160])
    return await _ask_once(state, questions, transport)


async def _ask_windowed(source: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    """One call per window, in parallel; the max score per question (an existence question is true if any window
    shows it, never diluted by the windows that don't)."""
    results = await asyncio.gather(*(_ask(_state(w), questions, transport) for w in _windows(source)))
    out: dict[str, float] = {k: 0.0 for k in questions}
    for r in results:
        for k, v in r.items():
            out[k] = max(out[k], v)
    return out


async def coverage(source: str, branches: list[str], transport=None) -> dict[str, float]:
    """P(the SOURCE sets out the criteria or management for each branch), one call per window."""
    if not branches:
        return {}
    qs = {f"b_{i}": {"type": "noul", "instructions": (
        "The SOURCE states the classification criteria or the management recommendations for this case of the "
        f"guideline (not only mentions it): {b}")} for i, b in enumerate(branches)}
    got = await _ask_windowed(source, qs, transport)
    return {b: got[f"b_{i}"] for i, b in enumerate(branches)}


def exact_signals(source: str, claims: list[tuple[str, str]]) -> list[bool]:
    """Per (quote, claim): whether the quote is an exact match whose numbers also match the claim. Logged
    alongside Jev's score, never used to approve a claim — a verbatim quote from a sibling branch or edition
    passes this fast path too, and only Jev can see that the context is wrong."""
    return [quote_in(source, q) and _numbers_covered(c, q) for q, c in claims]


async def evidence(source: str, claims: list[tuple[str, str]], transport=None) -> list[float]:
    """Per (quote, claim): P(the SOURCE states the claim for exactly the guideline, edition and category named),
    from whichever window shows it. Every claim goes to Jev — there is no exact-match shortcut (see
    exact_signals): a verbatim quote can belong to the wrong branch, edition or guideline, and only Jev's strict
    wording below can tell."""
    if not claims:
        return []
    qs = {f"c_{i}": {"type": "noul", "instructions": (
        "The SOURCE states this for exactly the guideline, edition and category named, with the same values "
        "(a statement the SOURCE makes only about a different category, edition or guideline does not count): "
        f"{c}")} for i, (_, c) in enumerate(claims)}
    got = await _ask_windowed(source, qs, transport)
    return [got[f"c_{i}"] for i in range(len(claims))]


async def relevance(results: list[dict], name: str, version: str, title: str = "", transport=None) -> list[float]:
    """P(each search result is about the named guideline, not a different guideline or topic), in one batched call
    over a single state listing every candidate (title, url, the start of its snippet). Raises on failure: the
    caller falls back to ordering without it."""
    if not results:
        return []
    ident = " ".join(f"{name} {version}".split())
    about = ident + (f" ({title})" if title else "")
    state = "SEARCH RESULTS:\n" + "\n\n".join(
        f"[{i}] {r.get('title', '')} — {r.get('url', '')} — {(r.get('content') or '')[:SNIPPET_MAX]}"
        for i, r in enumerate(results))
    qs = {f"r_{i}": {"type": "noul", "instructions": f"Result [{i}] is about {about}, not a different guideline or topic."}
          for i in range(len(results))}
    got = await _ask(state, qs, transport)
    return [got[f"r_{i}"] for i in range(len(results))]


def _answers_q(question: str, about: str) -> dict[str, dict[str, Any]]:
    head = f"The SOURCE, which is about {about}, contains" if about else "The SOURCE contains"
    return {"q": {"type": "noul", "instructions": f"{head} the answer to this question: {question}"}}


async def answers_best(material: str, question: str, about: str = "", transport=None) -> tuple[float, str]:
    """(P(the material answers the radiologist's question), the window that scored highest), one call per window.
    The caller grounds its answer on that window, so an answer late in a long source is never cut off. `about`
    (a guideline's name and version) scopes the question to that guideline: a page about something else does not
    count."""
    windows = _windows(material)
    q = _answers_q(question, about)
    results = await asyncio.gather(*(_ask(_state(w), q, transport) for w in windows))
    best = max(range(len(windows)), key=lambda i: results[i]["q"])
    return results[best]["q"], windows[best]


async def answers(material: str, question: str, transport=None, about: str = "") -> float:
    """P(the stored guideline material answers the radiologist's question)."""
    return (await answers_best(material, question, about, transport))[0]
