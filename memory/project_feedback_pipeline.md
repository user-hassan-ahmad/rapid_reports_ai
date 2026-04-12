---
name: Feedback Pipeline for Skill Sheet Learning
description: Four-mechanism feedback system (diff capture, thumbs up/down, N-use check-in, teach-me) with "silent by default" UX principle — template learning should be felt, not seen
type: project
---

## Design Principle

**Silent by default.** Autonomous template updates produce no user-visible notification. The learning history is discoverable when the radiologist is curious, never pushed. The learning should be felt, not seen — radiologist notices "my reports have been getting better" not "my template changed yesterday." Streaming update notifications cause second-hand anxiety and over-correction.

**Why:** Radiologists will worry that report variations are due to recent template edits, leading to overcorrection/undo cascading. The learning should be subconscious — like a good assistant that learns preferences without announcing every adjustment.

**Anti-feedback-loop.** Human edits are the signal, never the AI's output. One-way flow: human edits → skill sheet rules → AI generation. Never the reverse.

## Four Mechanisms

1. **Diff capture** — browser `copy` event on report container (catches both button click AND Cmd+C). Captures `ai_output` (frozen) + `final_output` (at copy) + `sections_modified` (computed from diff against skill sheet structure). Abandoned reports tracked via component unmount. Data model: `report_feedback` table. **Build in Iteration 4 — start accumulating immediately.**

2. **Post-copy thumbs up/down** — ephemeral toast after copy event, auto-dismiss 5s, one-click. Feeds `template_rating` aggregate. **Build in Iteration 6.**

3. **N-use check-in** — banner at use thresholds (5, 15, 30, exponential). "Working well" raises proposal threshold; "Needs tweaking" opens refine pre-loaded with LEARN findings. **Build in Iteration 6.**

4. **Teach me (LEARN mode)** — new maintenance agent mode running on periodic lint schedule, NOT gated by user feedback. Reads accumulated diffs, extracts consistent patterns (≥60%, ≥3 occurrences), proposes skill sheet rules. Surfaces via notification bell as teach-me prompts. On approval: calls `refine_skill_sheet` → `TemplateVersion` → reversible. **Build in Iteration 7.**

## User-Facing Surfaces

1. Post-copy toast (ephemeral, ignorable)
2. N-use check-in banner (periodic, dismissible)
3. Notification bell (teach-me prompts, T3 approvals only — very quiet, 1-2/week)
4. Learning history — **collapsed section on template page**: "Explore how your template has been learning (3 updates)" — opt-in curiosity, past tense framing, [Undo] per entry

**What radiologists do NOT see:** activity timeline, update notifications, LEARN outcomes, T1/T2 action announcements, confidence scores, implementation terminology.

## Key Architecture Decisions

- All updates go through existing `refine_skill_sheet` method — no new update mechanism
- All updates create `TemplateVersion` → reversible via learning history [Undo]
- LEARN mode is continuous/periodic, NOT gated by negative feedback
- Check-in "Needs tweaking" surfaces LEARN's accumulated findings immediately (acceleration, not gate)
- Check-in "Working well" raises evidence threshold (modulation, not suppression)
- Global patterns (same edit across 3+ templates) → propose promoting to global style guide, not per-template
- Browser copy event listener catches Cmd+C for keyboard-native radiologists

## Spec Location

Full spec: `docs/superpowers/specs/2026-04-12-feedback-pipeline-design.md`

## How to Apply

- **Iteration 4**: `report_feedback` + `template_rating` tables + copy event listener + unmount handler. Start accumulating data.
- **Iteration 6**: toast, check-in banner, notification bell, learning history UI.
- **Iteration 7**: LEARN mode + pattern detection + teach-me surfacing + calibration integration.

## Related

- `project_maintenance_agent.md` — LEARN is a new mode in the agent
- `project_autonomy_tier_model.md` — LEARN proposals follow the same T1/T2/T3 tiering
- `project_feedback_linting_design.md` — earlier partial analysis (which reports qualify, approval signals) — now superseded by this spec
