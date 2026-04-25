"""
Chat system prompt — principle-stated preamble + dynamic context envelope.

This module replaces the inline 100-line f-string that previously lived
in ``chat_about_report``. It mirrors the shape of
``quick_report_hardening.py``: a top-level constant carrying the static
principles, plus a composer function that wraps the dynamic blocks
(report draft, evidence, audit memory, audit-fix context) under a
single ``## Active context`` envelope with consistent H3 subsections.

See ``docs/superpowers/specs/2026-04-26-chat-prompt-revamp-design.md``
for the full design.
"""

from __future__ import annotations

import re
from typing import List


# ─────────────────────────────────────────────────────────────────────────────
# Static preamble — orientation + 5 numbered principles.
# ─────────────────────────────────────────────────────────────────────────────
# Every rule the model needs on every turn lives here. Tool-argument
# concerns (placeholder fills, attribution stripping) live on the
# Pydantic field descriptions of ``ChatStructuredActionItem`` instead,
# so the system prompt stays focused on routing, voice, and the source
# attribution protocol.

CHAT_PROMPT_PREAMBLE = """\
## Orientation

You are working alongside a radiologist on a draft report they have \
generated. Use British English throughout. Be concise; say so when you \
are uncertain rather than fabricate.

Every turn falls into one of three shapes:

- **A clinical question** — you answer, you do not edit.
- **A request to change the report** — you call \
`apply_structured_actions`, you do not write the rewrite as chat \
prose.
- **Evidence retrieval** — you call `search_external_guidelines` when \
Active Context is insufficient.

The principles below tell you how to act within each shape and how to \
keep your two voices — conversational reply and report-body content — \
distinct.

The radiologist owns the report. Your job is to help them refine it: \
surface evidence, propose well-formed edits, answer clinical questions \
clearly. You never publish to the report directly — every edit you \
propose is reviewed and applied by the radiologist via the \
structured-actions panel.


## Principle 1 — Address the clinician

The user-facing reply is for one person: the radiologist working on \
this report. Speak to them in clinical terms. Use light Markdown only \
where it aids scanning — **bold** for society names and key numerical \
thresholds, short bullet lists for multiple items, optional `###` \
subheadings in longer answers.

Do not narrate the system. Never refer to "Active Context", evidence \
blocks, retrieval, pipelines, the Sources panel, or whether you called \
a tool. Do not end with system-style trailers such as "no further \
action is required" or "the context fully covers this". The \
radiologist sees only your clinical content, never your process.


## Principle 2 — Two voices for two destinations

What you produce has two destinations, and each demands a different \
voice.

**Conversational reply to the radiologist.** Cite freely. Name the \
society, document, year, and threshold exactly as the evidence states \
them — that is how you answer clinical questions faithfully. Do not \
write inline `[1]`, `[2]` numeric citation markers; name sources by \
their proper names instead.

**Anything that lands in the report body** — including the `details` \
field of `apply_structured_actions`, which describes prose that will be \
integrated into the report. Strip attribution. The report is the \
radiologist's own clinical voice; it does not name societies, cite \
guideline numbers, or use "per X" / "as per X" phrasing. The evidence \
informs *what* you write; the report must not read as if the evidence \
wrote it.

The same evidence, the same finding — different voice depending on \
where it lands.


## Principle 3 — Decide once whether to apply

If the message describes a change to the report — any phrasing that \
asks you to alter, add to, remove from, restructure, or rewrite \
content — call `apply_structured_actions` in the same turn. Decompose \
the change into focused actions inside the tool call. Do not write \
the revised text as prose in the chat reply.

If the message is a clinical question, an evidence query, or a \
discussion of options without a chosen change, reply conversationally. \
The radiologist will follow up with an apply instruction if they want \
one.

When the wording is borderline — polite phrasing like "could you", \
"can you", "I think we should" attached to a clear edit — **default to \
applying.** The structured-actions panel previews every edit before \
it lands; the radiologist dismisses false positives. Defaulting to \
apply is cheaper than defaulting to discuss, because the radiologist \
sees the proposed edit either way and one path produces the artifact \
they wanted while the other makes them ask again.

**Never write the revised report text as a chat reply.** If you find \
yourself producing FINDINGS / IMPRESSION / TECHNIQUE prose in the \
conversational message, you are misrouted — emit the tool call \
instead.


## Principle 4 — Search only when evidence is missing

Use `search_external_guidelines` only when authoritative imaging \
guidance is needed and the evidence already in Active Context does \
not cover the topic. Do not call it for report edits, laterality \
fixes, typos, simple clinical questions, or anything answered by the \
evidence below.

Do not emit `search_external_guidelines` and `apply_structured_actions` \
in the same assistant message. Retrieve first; apply in the next turn \
if a change is then warranted.


## Principle 5 — Declare your sources

After your complete reply, on its own line, output exactly:

    <SOURCES_USED>["https://url1", "https://url2"]</SOURCES_USED>

List only the URLs you directly drew on, using the exact strings from \
Active Context's evidence passages. Output `[]` if no external sources \
informed your reply. This block is parsed by the UI; do not paraphrase \
it or move it elsewhere in the message.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# Matches a line that looks like a section header, regardless of style:
#   - ATX heading: `#` … `######` followed by space and content
#   - `=== TITLE ===` delimiter (any number of equals ≥ 3 on each side)
#   - `--- TITLE ---` delimiter (defensive; not currently used by helpers)
_HEADER_LINE_RE = re.compile(
    r"^\s*(?:"
    r"#{1,6}\s+\S.*"
    r"|"
    r"={3,}\s+\S.*?\s+={3,}"
    r"|"
    r"-{3,}\s+\S.*?\s+-{3,}"
    r")\s*$"
)


def _strip_leading_header(block: str) -> str:
    """
    Remove a single leading section-header line (ATX `#`–`######` heading or
    a `=== TITLE ===` / `--- TITLE ---` delimiter) plus any blank lines that
    immediately follow it.

    Conservative: only strips ONE header. If the block has no leading
    header (or starts with body content directly), the body is returned
    unchanged after surrounding whitespace is normalised.
    """
    if not block:
        return ""
    # Trim outer whitespace so we can locate the first content-bearing line.
    s = block.strip("\n").rstrip()
    if not s:
        return ""
    # Inspect the first line. If it's a header, drop it; otherwise pass through.
    lines = s.split("\n", 1)
    first = lines[0]
    rest = lines[1] if len(lines) > 1 else ""
    if _HEADER_LINE_RE.match(first):
        # Drop blank lines between the stripped header and the next content.
        return rest.lstrip("\n").rstrip()
    return s


def _wrap_audit_fix_mode(audit_holistic_block: str) -> str:
    """
    Promote ``audit_holistic_block`` (workflow instructions for audit-fix
    turns) to its own ``## Audit-fix mode`` H2 between the principles and
    Active context. The existing helper emits its own H2; we strip that and
    apply the consistent ``## Audit-fix mode`` header.

    Returns an empty string if the input has no body content.
    """
    body = _strip_leading_header(audit_holistic_block)
    if not body:
        return ""
    return f"## Audit-fix mode\n\n{body}"


def _build_active_context(
    *,
    report_content: str,
    enhancement_context: str,
    audit_memory_block: str,
    audit_fix_block: str,
) -> str:
    """
    Compose ``## Active context`` with named H3 subsections. Each
    subsection renders only when its corresponding input is non-empty.

    The envelope strips each existing block helper's internal heading
    (e.g. ``=== EVIDENCE CONTEXT ===``, ``## AUDIT QA GROUNDING``) and
    applies a consistent H3 of its own, so the model sees one grammar
    across blocks.

    If every block is empty, the ``## Active context`` H2 itself is
    omitted — caller receives an empty string.
    """
    subsections: List[str] = []

    report_body = (report_content or "").strip()
    if report_body:
        subsections.append(f"### Report draft\n\n{report_body}")

    evidence_body = _strip_leading_header(enhancement_context)
    if evidence_body:
        subsections.append(f"### Evidence retrieved\n\n{evidence_body}")

    memory_body = _strip_leading_header(audit_memory_block)
    if memory_body:
        subsections.append(f"### Audit memory\n\n{memory_body}")

    fix_body = _strip_leading_header(audit_fix_block)
    if fix_body:
        subsections.append(f"### Audit fix in progress\n\n{fix_body}")

    if not subsections:
        return ""

    header = (
        "## Active context\n\n"
        "The sections below are the working material for this turn. "
        "Each appears only when relevant; absence means there is "
        "nothing of that kind to consider."
    )
    return "\n\n".join([header, *subsections])


def build_chat_system_prompt(
    *,
    report_content: str,
    enhancement_context: str,
    audit_memory_block: str,
    audit_holistic_block: str,
    audit_fix_block: str,
) -> str:
    """
    Compose the full chat system prompt: static principles, optional
    audit-fix mode H2, and Active context envelope.

    Pure function — given identical inputs, returns identical output.
    Tested in ``backend/tests/test_chat_prompt.py``.
    """
    parts: List[str] = [CHAT_PROMPT_PREAMBLE]

    audit_fix_mode = _wrap_audit_fix_mode(audit_holistic_block)
    if audit_fix_mode:
        parts.append(audit_fix_mode)

    active_context = _build_active_context(
        report_content=report_content,
        enhancement_context=enhancement_context,
        audit_memory_block=audit_memory_block,
        audit_fix_block=audit_fix_block,
    )
    if active_context:
        parts.append(active_context)

    # Join with a single blank line between top-level regions; never produce
    # three or more consecutive newlines.
    composed = "\n\n".join(p.rstrip() for p in parts if p.strip())
    return re.sub(r"\n{3,}", "\n\n", composed)
