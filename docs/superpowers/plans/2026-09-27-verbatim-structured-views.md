# Plan — Verbatim and Structured as two views (2026-09-27)

**Why:** the toggle re-polished the one scratchpad in the other mode and overwrote it. Switching back re-ran the verbatim polish on bullets, which keeps existing text, so the verbatim text was lost for good (lab, 2026-09-27; production has the same code).

**Decisions (user, 2026-09-27):** Verbatim is the source of truth. Hand edits made in Structured are kept until the verbatim text changes; the next rebuild then replaces them, with a notice. Generate Report uses the view on screen.

## Design

- The existing editor always holds the verbatim text. Dictation, polish (always `clean`), racing, undo, outcome tracking and review work on it unchanged, whichever view is showing.
- A second editor holds the structured text, shown only in Structured view. It is derived by `POST /api/canvas/process` in `structured` mode, with the verbatim text as the transcript and an empty scratchpad (no backend change).
- The rebuild runs 1.5 s after the verbatim text settles, never while a final is faded or a polish is pending, and only once Structured has been used in the session (no extra calls for users who never switch). A result for text that has since changed is discarded.
- Switching is instant both ways when the structured text is current; otherwise Structured shows "Updating…" over the previous version (or a placeholder) and builds at once.
- `getContent()`, `onContentChange` and the margin follow the view on screen.

## Tasks (TDD, one commit each)

1. `structuredView.ts`: pure state — current / should build / accept (stale discarded; edits-replaced flag) / note edit. Tests.
2. Scratchpad: second editor, view switch, rebuild scheduler, notice; live polish always `clean`.
3. Docs (handover).

Known limits: a draft saved in Structured view restores that text as the verbatim text; margin cards anchored to verbatim wording may not find their text in Structured view.
