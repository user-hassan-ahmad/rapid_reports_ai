# Chat System Prompt Revamp

Spec for restructuring the `/api/reports/{id}/chat` system prompt from an
inline 100-line f-string into a principle-stated module mirroring
`quick_report_hardening.py`, with a consistent dynamic-block envelope
and tool-argument rules migrated to Pydantic field descriptions.

## Background and motivation

The chat module has accreted instruction layers over six months without
restructuring. Three commits in particular added content to the system
prompt without re-anchoring its shape:

- `c825050` — added the *Evidence context use* block (~7 lines).
- `f042952` — added the *Composing details — no attribution* block
  (~9 lines).
- Various earlier commits added the *Source attribution / SOURCES_USED*
  protocol, the three-state routing matrix, and the *Filling
  placeholders* rules.

The current prompt has eight peer-level `##` sections covering routing,
evidence handling, attribution, composition, output protocol, and
style. The flat structure puts a layout rule (*"don't mention pipelines"*)
at the same visual weight as a routing rule (*"call apply_structured_actions
when the user asks to modify"*), which contributes to qwen3-32b's tool-call
flakiness — the failure mode salvaged in `71fbd41` (rewrite-as-prose with
no tool call) is partially attributable to ambiguous routing across two
layers (the tool description and the system prompt) that disagree on
borderline messages.

Six structural problems in the current prompt:

1. **No primacy / orientation statement.** The model has no anchor for
   which constraint to bend when two collide.
2. **Flat heading hierarchy hides what's load-bearing.** Eight peer `##`
   sections mix routing, content, output protocol, and style with equal
   visual weight.
3. **Routing rules split between two layers.** The `apply_structured_actions`
   tool description and the system prompt's three-state matrix nearly
   contradict on borderline messages.
4. **Composition rules at the wrong level.** Attribution and placeholder
   rules are tool-argument concerns living in the global system prompt,
   weighed on every turn including pure conversational ones.
5. **Dynamic blocks concatenated raw.** `enhancement_context`,
   `audit_memory_block`, `audit_holistic_block`, `audit_fix_block`, and
   `report.report_content` are appended at the tail with no consistent
   framing — each emits its own internal heading style.
6. **Defensive framing dominates.** Seven "never" / "do not" rules and
   only sparse positive instructions; the model develops a defensive
   posture that suppresses tool calls on borderline cases.

The salvage path shipped in `71fbd41` catches the worst failure mode at
runtime. This revamp addresses it at the structural level — fewer
salvage events, clearer model behaviour on first-pass, and a prompt
shape that future additions slot into without re-introducing accretion.

## Design principles

- **Mirror an existing pattern in the codebase.** Match the style of
  `quick_report_hardening.py`: a top-level constant for principles +
  composition function for dynamic context. No new architectural
  concept.
- **Principles are positive statements with bans as corollaries.** Each
  principle states what the model *is doing* before listing what it
  must not do. Reduces the seven-bans-in-100-lines defensive posture.
- **Single source of truth for routing.** The system prompt owns
  routing; the tool description describes the tool. They cannot
  contradict because they no longer overlap.
- **Tool-argument rules ship with the tool.** Composition rules
  (attribution, placeholder fills) move from the system prompt to
  the Pydantic field descriptions on `ChatStructuredActionItem`. They
  apply only when the model is filling those fields.
- **Consistent dynamic-block envelope.** All context blocks render
  under one `## Active context` H2 with named H3 subsections. The
  envelope helper strips internal headers from existing blocks and
  applies its own — existing helpers untouched.
- **Default to apply on borderline routing.** The salvage path catches
  misroutes; the structured-actions UI lets the radiologist dismiss
  false positives. A bias toward applying is cheaper than discussing
  when the user wanted an apply.

## Scope

### In scope

1. New module `backend/src/rapid_reports_ai/chat_prompt.py` containing
   the principle-stated preamble constant, the `build_chat_system_prompt`
   composer, the `_build_active_context` envelope helper, and the
   `_strip_leading_header` normaliser.
2. Updated `chat_about_report` handler in `main.py` — replaces the
   inline f-string with a single call to `build_chat_system_prompt`.
3. Updated tool definition for `apply_structured_actions` in
   `main.py`'s `tools` list — slimmed description, no routing rules.
4. Updated tool definition for `search_external_guidelines` —
   "ENHANCEMENT CONTEXT" renamed to "Active Context" for consistency
   with the new envelope.
5. Updated Pydantic field descriptions on `ChatStructuredActionItem.title`,
   `ChatStructuredActionItem.details`, and
   `ChatStructuredActionsRequest.conversation_summary` — composition
   rules migrated here from the system prompt.
6. Refactor of the salvage path's local `apply_structured_actions` tool
   definition (in the salvage block at `main.py`) to share a single
   `_apply_structured_actions_tool_def()` helper with the primary tools
   list, so descriptions cannot drift.
7. Unit tests for `chat_prompt.py` covering: empty-block omission in
   the envelope, header stripping correctness, presence/absence of the
   audit-fix mode H2 based on whether `audit_holistic_block` is non-empty.

### Out of scope (deliberately)

- Refactoring the existing helper functions (`build_chat_guideline_context`,
  `build_audit_guideline_references_memory_section`,
  `format_audit_fix_holistic_workflow_instructions`,
  `format_audit_fix_context_for_system_prompt`) to return body-only
  content. The envelope strips at the seam instead — minimal blast
  radius. Considered as option (b) during brainstorming, rejected.
- Changing the routing model (still qwen3-32b on Groq).
- Changing the salvage detection signals or thresholds.
- Loading the principles from a sibling `.md` file. Considered during
  brainstorming, rejected in favour of a Python constant for parity with
  `quick_report_hardening.py` and to avoid startup I/O.
- Modifying the executor (`regenerate_report_with_actions`) or its
  prompt — the executor is downstream of this work.
- Frontend changes. The chat handler's response shape is unchanged.

## Architecture

### Module layout

```
backend/src/rapid_reports_ai/
├── chat_prompt.py                 ← NEW
│   ├── CHAT_PROMPT_PREAMBLE       (constant: orientation + 5 principles)
│   ├── build_chat_system_prompt   (composer)
│   ├── _build_active_context      (envelope helper)
│   ├── _wrap_audit_fix_mode       (audit-fix H2 wrapper)
│   └── _strip_leading_header      (normaliser for existing block headers)
└── main.py                        ← MODIFIED
    ├── chat_about_report          (calls build_chat_system_prompt)
    ├── ChatStructuredActionItem   (updated field descriptions)
    ├── ChatStructuredActionsRequest (updated field descriptions)
    └── _apply_structured_actions_tool_def (shared between main + salvage)
```

### Composer flow

```
build_chat_system_prompt(
    report_content,
    enhancement_context,
    audit_memory_block,
    audit_holistic_block,
    audit_fix_block,
)
  ↓
parts = [CHAT_PROMPT_PREAMBLE]
if audit_holistic_block: parts.append(_wrap_audit_fix_mode(...))
parts.append(_build_active_context(report, evidence, memory, audit_fix))
return "\n\n".join(p.rstrip() for p in parts if p.strip())
```

The composer is a pure function. Tests can pass arbitrary block
combinations and assert on the resulting structure.

## The principle-stated preamble

The constant `CHAT_PROMPT_PREAMBLE` contains an Orientation paragraph
followed by five numbered principles, drafted in full during
brainstorming and approved.

### Orientation

```markdown
## Orientation

You are working alongside a radiologist on a draft report they have
generated. Use British English throughout. Be concise; say so when you
are uncertain rather than fabricate.

Every turn falls into one of three shapes:

- **A clinical question** — you answer, you do not edit.
- **A request to change the report** — you call
  `apply_structured_actions`, you do not write the rewrite as chat
  prose.
- **Evidence retrieval** — you call `search_external_guidelines` when
  Active Context is insufficient.

The principles below tell you how to act within each shape and how to
keep your two voices — conversational reply and report-body content —
distinct.

The radiologist owns the report. Your job is to help them refine it:
surface evidence, propose well-formed edits, answer clinical questions
clearly. You never publish to the report directly — every edit you
propose is reviewed and applied by the radiologist via the
structured-actions panel.
```

### Principle 1 — Address the clinician

```markdown
## Principle 1 — Address the clinician

The user-facing reply is for one person: the radiologist working on
this report. Speak to them in clinical terms. Use light Markdown only
where it aids scanning — **bold** for society names and key numerical
thresholds, short bullet lists for multiple items, optional `###`
subheadings in longer answers.

Do not narrate the system. Never refer to "Active Context", evidence
blocks, retrieval, pipelines, the Sources panel, or whether you called
a tool. Do not end with system-style trailers such as "no further
action is required" or "the context fully covers this". The
radiologist sees only your clinical content, never your process.
```

### Principle 2 — Two voices for two destinations

```markdown
## Principle 2 — Two voices for two destinations

What you produce has two destinations, and each demands a different
voice.

**Conversational reply to the radiologist.** Cite freely. Name the
society, document, year, and threshold exactly as the evidence states
them — that is how you answer clinical questions faithfully. Do not
write inline `[1]`, `[2]` numeric citation markers; name sources by
their proper names instead.

**Anything that lands in the report body** — including the `details`
field of `apply_structured_actions`, which describes prose that will be
integrated into the report. Strip attribution. The report is the
radiologist's own clinical voice; it does not name societies, cite
guideline numbers, or use "per X" / "as per X" phrasing. The evidence
informs *what* you write; the report must not read as if the evidence
wrote it.

The same evidence, the same finding — different voice depending on
where it lands.
```

### Principle 3 — Decide once whether to apply

```markdown
## Principle 3 — Decide once whether to apply

If the message describes a change to the report — any phrasing that
asks you to alter, add to, remove from, restructure, or rewrite
content — call `apply_structured_actions` in the same turn. Decompose
the change into focused actions inside the tool call. Do not write
the revised text as prose in the chat reply.

If the message is a clinical question, an evidence query, or a
discussion of options without a chosen change, reply conversationally.
The radiologist will follow up with an apply instruction if they want
one.

When the wording is borderline — polite phrasing like "could you",
"can you", "I think we should" attached to a clear edit — **default to
applying.** The structured-actions panel previews every edit before
it lands; the radiologist dismisses false positives. Defaulting to
apply is cheaper than defaulting to discuss, because the radiologist
sees the proposed edit either way and one path produces the artifact
they wanted while the other makes them ask again.

**Never write the revised report text as a chat reply.** If you find
yourself producing FINDINGS / IMPRESSION / TECHNIQUE prose in the
conversational message, you are misrouted — emit the tool call
instead.
```

### Principle 4 — Search only when evidence is missing

```markdown
## Principle 4 — Search only when evidence is missing

Use `search_external_guidelines` only when authoritative imaging
guidance is needed and the evidence already in Active Context does
not cover the topic. Do not call it for report edits, laterality
fixes, typos, simple clinical questions, or anything answered by the
evidence below.

Do not emit `search_external_guidelines` and `apply_structured_actions`
in the same assistant message. Retrieve first; apply in the next turn
if a change is then warranted.
```

### Principle 5 — Declare your sources

```markdown
## Principle 5 — Declare your sources

After your complete reply, on its own line, output exactly:

    <SOURCES_USED>["https://url1", "https://url2"]</SOURCES_USED>

List only the URLs you directly drew on, using the exact strings from
Active Context's evidence passages. Output `[]` if no external sources
informed your reply. This block is parsed by the UI; do not paraphrase
it or move it elsewhere in the message.
```

## The dynamic-block envelope

After the static preamble, the prompt continues with two regions:

```markdown
## Audit-fix mode  ← only present when audit_fix_context is set
…workflow instructions for audit-fix turns (audit_holistic_block)…

## Active context

The sections below are the working material for this turn. Each
appears only when relevant; absence means there is nothing of that
kind to consider.

### Report draft
…report.report_content verbatim…

### Evidence retrieved
…enhancement_context body, leading header normalised away…

### Audit memory
…audit_memory_block body, normalised…

### Audit fix in progress
…audit_fix_block body, normalised…
```

### Block-to-subsection mapping

| Existing block | New location | Notes |
|---|---|---|
| `report.report_content` | `### Report draft` (under Active context) | Verbatim. |
| `enhancement_context` | `### Evidence retrieved` | Internal header stripped by `_strip_leading_header`. |
| `audit_memory_block` | `### Audit memory` | Internal header stripped. |
| `audit_fix_block` | `### Audit fix in progress` | Internal header stripped. |
| `audit_holistic_block` | `## Audit-fix mode` (between principles and Active context) | Promoted to its own H2 — this block is workflow instructions, not data, and belongs at instruction-layer scope. |

### Header normalisation

`_strip_leading_header(block: str) -> str`:

- If `block` starts (after optional whitespace) with an ATX heading
  line (any of `#` through `######`) followed by a newline, drop that
  line and any subsequent blank lines.
- Otherwise return `block.strip()` unchanged.
- Conservative: only strips one heading. If a block starts with no
  heading, returns body-only content.

### Empty-block handling

Each subsection inside Active context renders only when its
corresponding input is non-empty after `.strip()`. If all four
subsections are empty (rare — there is always a `report.report_content`),
the `## Active context` header itself is omitted.

`## Audit-fix mode` renders only when `audit_holistic_block` is
non-empty. The block is currently emitted by
`format_audit_fix_holistic_workflow_instructions()` only when
`request.audit_fix_context` is set, so this gates correctly without
extra logic.

## Pydantic field description migrations

### `apply_structured_actions` tool description

Slimmed; routing rules removed (owned by Principle 3).

```python
{
    "type": "function",
    "function": {
        "name": "apply_structured_actions",
        "description": (
            "Propose a structured set of edits to the radiology report. "
            "Each action is one focused change with a title and a "
            "details field. Use when the user's message describes a "
            "change to the report — alter, add, remove, restructure, "
            "or rewrite content. Do not use for clinical questions or "
            "evidence retrieval."
        ),
        "parameters": ChatStructuredActionsRequest.model_json_schema(),
    },
}
```

### `ChatStructuredActionItem.title.description`

Adds grounded examples.

```python
title: str = Field(
    ...,
    description=(
        "One-line description of what this action changes — e.g. "
        "'Update TNM staging to T2N0M0', 'Tighten Findings into a "
        "single paragraph', 'Insert follow-up recommendation after "
        "liver finding'."
    ),
)
```

### `ChatStructuredActionItem.details.description`

Absorbs the migrated *Composing details* and *Filling placeholders*
content.

```python
details: str = Field(
    ...,
    description=(
        "What to change and why. Any prose you write here that is "
        "intended for insertion into the report body must follow "
        "Principle 2 — no source attribution: no society names "
        "(NICE, ACR, Fleischner, RCR), no guideline numbers (e.g. "
        "NG147, 1.3.10), no 'per X' or 'as per X' phrasing. The "
        "radiologist's voice owns the report; the reasoning portion "
        "of this field may reference sources for justification, but "
        "the prose-to-insert must stand alone.\n\n"
        "For placeholder fills ('xxx mm', '{VARIABLE}'): use an "
        "explicit value from the report findings if present; "
        "otherwise apply a clinically appropriate normal/reference "
        "value for the anatomy and modality, and note in this field "
        "whether the value was taken from the report or is a "
        "reference value requiring verification. Never refuse to fill "
        "a placeholder — always apply something and surface the basis."
    ),
)
```

### `ChatStructuredActionsRequest.conversation_summary.description`

```python
conversation_summary: Optional[str] = Field(
    None,
    description=(
        "Optional 1-2 sentence summary of relevant prior turns. Helps "
        "the executor model understand context the current message "
        "alone doesn't carry. Skip if the user's current message is "
        "self-contained."
    ),
)
```

### `search_external_guidelines` tool description

"ENHANCEMENT CONTEXT" → "Active Context" rename only; routing reasoning
stays.

```python
{
    "type": "function",
    "function": {
        "name": "search_external_guidelines",
        "description": (
            "Search authoritative web sources for UK-relevant imaging "
            "guidance. Use only when Active Context's evidence does "
            "not cover the topic (e.g. specific staging, "
            "classification, society guideline). Do not use for "
            "report edits or questions already answered by available "
            "evidence."
        ),
        "parameters": SearchExternalGuidelinesRequest.model_json_schema(),
    },
}
```

### Shared tool-definition helper

A single `_apply_structured_actions_tool_def()` helper returns the dict
for both the primary `tools` list and the salvage path's `salvage_tools`
list. Same approach for `_search_external_guidelines_tool_def()`.

```python
def _apply_structured_actions_tool_def() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "apply_structured_actions",
            "description": "...",
            "parameters": ChatStructuredActionsRequest.model_json_schema(),
        },
    }
```

## Testing

Unit tests covering `chat_prompt.py` (`backend/tests/test_chat_prompt.py`).
The composer is a pure function — no mocks needed.

| Test | Asserts |
|---|---|
| `test_preamble_includes_all_principles` | The constant contains `## Principle 1` … `## Principle 5` and `## Orientation`. |
| `test_active_context_renders_when_all_blocks_present` | All four H3 subsections appear in output, in declared order. |
| `test_active_context_omits_empty_blocks` | When only `report_content` is non-empty, only `### Report draft` renders; no other H3s appear. |
| `test_active_context_header_omitted_when_all_blocks_empty` | When every block including report is empty, `## Active context` does not appear. (Edge case; defensive.) |
| `test_audit_fix_mode_renders_only_when_holistic_set` | When `audit_holistic_block` is non-empty, `## Audit-fix mode` appears between principles and Active context; otherwise absent. |
| `test_strip_leading_header_removes_h2` | `_strip_leading_header("## EVIDENCE\n\nbody")` → `"body"`. |
| `test_strip_leading_header_removes_h1` | `_strip_leading_header("# EVIDENCE\n\nbody")` → `"body"`. |
| `test_strip_leading_header_removes_deeper_levels` | `_strip_leading_header("### EVIDENCE\n\nbody")` → `"body"`; same for `####` etc. |
| `test_strip_leading_header_passthrough_when_no_header` | `_strip_leading_header("body only")` → `"body only"`. |
| `test_strip_leading_header_only_strips_one` | `_strip_leading_header("## A\n\n## B\n\nbody")` → `"## B\n\nbody"`. |
| `test_composer_no_double_blank_lines` | Output never contains three or more consecutive newlines. |

No integration test of `chat_about_report` itself — that handler's
behaviour beyond prompt composition is unchanged. The prompt is asserted
in isolation.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Existing block helpers may emit headers we don't anticipate (e.g. setext-style underlines, all-caps prefixes). | `_strip_leading_header` only strips ATX `#`/`##` headers; anything else passes through, preserving content. The H3 we add will simply sit above whatever the block emits. Worst case: minor cosmetic redundancy; no information loss. Verified during implementation by inspecting actual outputs of all four helpers. |
| Default-to-apply (Principle 3) increases false-positive tool calls. | The structured-actions UI previews every edit before it lands; the radiologist dismisses false positives. Salvage logs from `71fbd41` are already capturing rewrite-as-prose events; we'll watch the inverse signal (tool-called when user wanted discussion) for the first week post-deploy. |
| Routing centralisation in Principle 3 may interact poorly with the `apply_structured_actions` tool description. | Tool description deliberately drops routing rules — only Principle 3 owns routing. Tool description is informational ("what does this tool do") not directive ("when do I use it"). |
| Salvage path's local tool definition drifts from the primary one. | Both paths now go through `_apply_structured_actions_tool_def()`. Single source of truth. |
| Migration of placeholder rules to `details.description` may not be visible to qwen on every turn. | Pydantic field descriptions are part of the JSON schema attached to the tool; they ship with the tool definition on every turn the tool is exposed. They're seen by qwen identically to the system prompt for tool-call decisions. |

## Rollout

Single PR. No feature flag — the change is structural and either works
or doesn't. Verification:

1. Local: run the unit tests; confirm a manual chat turn against a
   known report produces a valid system prompt by logging
   `len(system_prompt)` and a head/tail snippet.
2. Staging or local uvicorn: send three test messages —
   - Pure clinical question ("what's the Fleischner threshold for solid
     nodules?"): expect conversational reply, no tool call.
   - Direct edit ("change right to left in finding 2"): expect
     `apply_structured_actions` call.
   - Borderline ("could you tighten the impression a bit?"): expect
     `apply_structured_actions` call (Principle 3 default).
3. Production: deploy and monitor `🛟 SALVAGE` logs for 48 hours.
   Expectation is fewer salvage triggers compared to baseline; if the
   trigger rate increases instead, that signals a regression in
   first-pass routing.

## Migration / data concerns

None. This is a prompt-structure change. No database migration, no API
contract change, no frontend impact.

## Open questions

None remaining at spec-writing time. All design decisions resolved
during brainstorming.
