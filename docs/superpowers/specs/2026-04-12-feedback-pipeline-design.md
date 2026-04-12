# Feedback Pipeline for Skill Sheet Learning

Spec for implementing continuous, subconscious template improvement through four feedback mechanisms that capture radiologist behaviour and feed it into the skill sheet refinement loop.

## Design Principle

**Silent by default.** Template learning should be felt, not seen. The radiologist should notice "my reports have been getting better" — not "my template changed yesterday." Autonomous updates produce no user-visible notification. The learning history is discoverable when the radiologist is curious, never pushed. Items requiring input (teach-me prompts, approvals, check-ins) surface sparingly via a notification bell that is quiet most of the time.

**Anti-feedback-loop.** Human edits are the signal, never the AI's output. The diff is between what the AI generated and what the radiologist committed. Skill sheet updates are derived from human correction patterns. One-way information flow: human edits → skill sheet rules → AI generation. Never the reverse.

## Four Mechanisms

### Mechanism 1 — Diff Capture

The foundation. Captures the delta between AI-generated output and the radiologist's committed version.

**Trigger: browser `copy` event on the report container.** Fires on both the copy button click AND Cmd+C / Cmd+A+Cmd+C from keyboard-native radiologists. Detection logic: listen for `copy` events, check if `window.getSelection()?.toString()` covers >50% of the report text length. If so, treat as a report copy and capture the feedback.

The existing copy button handler stays as a parallel capture path. Both paths write to the same `report_feedback` row.

**Abandoned detection:** On component unmount or route navigation, if the report was generated or edited but never copied, mark `lifecycle: 'abandoned'`. Weak negative signal — counted in template-level aggregates but not used for diff-based skill sheet refinement.

**Multiple copies:** A radiologist may copy, paste into RIS, notice something, come back, edit, copy again. Each copy event overwrites `final_output` and bumps `copy_count`. Only the last copy within a session is used for diff analysis.

**What gets captured:**

```sql
CREATE TABLE report_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID,                      -- nullable: not all generation flows persist a report row
    template_id UUID NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Captured state
    ai_output TEXT NOT NULL,          -- original AI generation, frozen at generation time
    final_output TEXT,                -- editor state at last copy, updated on each copy event

    -- Lifecycle
    lifecycle TEXT NOT NULL DEFAULT 'generated',  -- generated | edited | copied | abandoned
    copy_count INT DEFAULT 0,

    -- Direct feedback (Mechanism 2)
    rating TEXT,                      -- positive | negative | null (not rated)

    -- Implicit signals
    time_to_first_edit_ms INT,
    time_to_copy_ms INT,
    edit_distance INT,                -- Levenshtein or similar, computed on capture
    sections_modified TEXT[],         -- which skill sheet sections were touched, computed from diff

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON report_feedback (template_id);
CREATE INDEX ON report_feedback (user_id, template_id);
CREATE INDEX ON report_feedback (lifecycle);
```

**`sections_modified` computation:** The skill sheet's `## Structural Pattern` defines sections. The diff between `ai_output` and `final_output` is mapped back to which sections were edited by aligning section boundaries from the original generated report. This gives section-level signal without any explicit per-section feedback UI — the diff IS the section-level feedback.

**Timing:** Build in Iteration 4 alongside `generate_report_from_config` verification. Start accumulating data immediately, even before any analysis pipeline exists. By the time LEARN mode lands, there are weeks of data to analyze.

### Mechanism 2 — Post-Copy Thumbs Up/Down

A one-click, non-blocking report-level quality signal.

**Trigger:** After the copy event fires, a small toast slides in from the bottom-right corner of the report area. Auto-dismisses after 5 seconds if not interacted with.

```
How was this report?   [👍]  [👎]
```

One click writes `rating` to the existing `report_feedback` row. No modal, no text input, no follow-up. If ignored, `rating` stays null — treated as neutral.

**What it feeds:** Template-level aggregate stats. A template with 80% positive ratings and low edit distances is working well; one with 40% negative and high edit distances needs attention. This modulates the maintenance agent's confidence in proposing updates and influences the N-use check-in timing.

**What it does NOT do:**
- No per-section feedback annotations (hover → "Too verbose" etc.). The diff captures section-level signal automatically.
- No regeneration from feedback. The radiologist edits directly; they don't need a "regenerate with corrections" workflow that forks the flow.
- No assertions or change requests. Those route through the teach-me mechanism when patterns accumulate.

### Mechanism 3 — Template-Level Rating (N-Use Check-In)

An accumulated-perception check-in after enough uses to form a meaningful opinion, filtering out per-report noise.

**When it surfaces:** At use thresholds: 5, 15, 30, then exponentially decreasing. Not every N uses. A small collapsible banner at the top of the report area when using that template:

```
You've used "CT Staging Colorectal — Dr Smith" 5 times.
[Working well ✓]    [Needs tweaking ✎]    [Dismiss]
```

**Behaviour per option:**

- **Working well** → records positive signal in `template_rating`, reduces the maintenance agent's proposal frequency for this template. Agent notes: "radiologist is satisfied, raise the evidence threshold before proposing changes." Dismisses the banner.
- **Needs tweaking** → opens the skill sheet refine flow, pre-loaded with the maintenance agent's accumulated LEARN mode findings for this template. The agent has already been analyzing diffs in the background; now it presents its findings: "I noticed you consistently add X, remove Y, restructure Z. Want me to update the template?" This is the bridge between passive diff capture and active refinement.
- **Dismiss** → hides the banner for this check-in cycle, no signal recorded. Agent continues as normal.

**Data model:**

```sql
CREATE TABLE template_rating (
    template_id UUID NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_uses INT DEFAULT 0,
    positive_count INT DEFAULT 0,          -- thumbs-up count
    negative_count INT DEFAULT 0,          -- thumbs-down count
    avg_edit_distance FLOAT DEFAULT 0,
    last_check_in_at TIMESTAMPTZ,
    last_check_in_uses INT DEFAULT 0,      -- how many uses when last prompted
    last_rating TEXT,                       -- working_well | needs_tweaking | null
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (template_id, user_id)
);
```

### Mechanism 4 — Teach Me (Pattern Detection + Intelligent Surfacing)

The mechanism that ties everything together. Detects consistent edit patterns across reports and proposes durable skill sheet rules.

**How it works:**

1. **Diff capture accumulates** over time (Mechanism 1, running since Iteration 4).
2. **LEARN mode runs on a periodic schedule** — part of the maintenance agent's lint pass (nightly or weekly). NOT gated by user feedback. Runs regardless of template rating.
3. **LEARN mode reads accumulated diffs** for each template with new feedback since last run. Extracts consistent patterns:
   - "In 7/10 CT Chest reports, you added 'Clinical correlation recommended' to the impression"
   - "In 4/5 MRI Knee reports, you removed the Goutallier grading from the impression but kept it in findings"
   - "You consistently change 'There is no' to 'No' at the start of negative sentences"
4. **Before proposing, LEARN mode checks:**
   - Does this pattern already exist as a rule in the skill sheet? (Don't re-propose)
   - Does this pattern conflict with the global style guide? (Flag conflict, don't propose conflicting rule)
   - Is the pattern consistent enough? (Threshold: ≥60% of recent reports with edits, minimum 3 occurrences)
   - Has a similar proposal been rejected before? (Don't re-propose — inviolable rule 4)
   - Is this a global pattern or template-specific? (If the same edit appears across 3+ templates, propose promoting to the global style guide instead)
5. **Surfacing — via notification bell only.** A quiet notification: "I noticed you consistently add a Clinical Correlation section in CT Chest reports. Should I make this a rule?" One-click approve / dismiss.
6. **On approval:** The maintenance agent calls `refine_skill_sheet` with the proposed rule as the refinement instruction. Creates a new `TemplateVersion`. Fully reversible via the learning history.

**LEARN mode is a new maintenance agent mode** alongside DISCOVER/REIFY/ACQUIRE/etc. Same system prompt, same inviolable rules ("always quote evidence"), same proposal output format. Subject to the same autonomy tier model:
- First-sighting LEARN proposals are T3 (radiologist approves via notification)
- After calibration, LEARN proposals for the same pattern type can earn T2 (applied autonomously, visible in learning history) or T1 (fully silent)

**Anti-hallucination safety:** LEARN mode can only propose rules **directly evidenced in the diffs** — quoted text the radiologist added, removed, or changed. The proposal includes evidence ("you did X in reports on [date], [date], [date]"). No abstracted or inferred rules.

**Relationship to check-in (Mechanism 3):**
- LEARN mode runs continuously on a schedule, regardless of check-in status
- "Needs tweaking" at a check-in surfaces LEARN mode's *already-accumulated* findings immediately, in context, as a pre-loaded refine session
- "Working well" at a check-in raises the evidence threshold for future LEARN proposals (agent needs stronger patterns before suggesting changes)
- No check-in interaction at all: LEARN mode still runs, still surfaces teach-me prompts via the notification bell when evidence is strong enough

## Aggregation Pipeline — End-to-End Flow

```
Report generated
    │
    ├── Radiologist edits → diff accumulates in editor state
    │
    ├── Copy event fires (button or Cmd+C)
    │       → report_feedback row: ai_output + final_output + sections_modified
    │       → lifecycle = 'copied'
    │       → template_rating.total_uses++
    │
    ├── Post-copy toast → optional thumbs up/down
    │       → report_feedback.rating
    │       → template_rating.positive_count / negative_count
    │
    ├── Component unmount without copy
    │       → report_feedback.lifecycle = 'abandoned'
    │
    └── N-use threshold reached
            → check-in banner surfaces
                ├── "Working well" → raise proposal threshold
                ├── "Needs tweaking" → open refine with LEARN findings
                └── Dismiss → no signal


Continuous background (periodic lint pass, nightly/weekly):
    │
    └── LEARN mode runs per template
            │
            ├── Reads accumulated diffs since last run
            ├── Extracts consistent patterns
            ├── Checks against existing rules + rejection log + global style guide
            │
            ├── Strong pattern (≥60%, ≥3 occurrences)
            │       → notification bell: teach-me prompt
            │       → on approve: refine_skill_sheet(rule) → TemplateVersion
            │       → on dismiss: logged, not re-proposed
            │
            └── Weak/insufficient pattern
                    → logged internally, checked again next run with more data
```

## User-Facing Surfaces

### What the radiologist sees

1. **Post-copy toast** — ephemeral, one-click thumbs up/down, auto-dismiss after 5 seconds. Appears after every copy event. Ignorable.

2. **N-use check-in banner** — appears at use thresholds (5, 15, 30, exponentially decreasing). Three options: Working well / Needs tweaking / Dismiss. Minimally intrusive, dismissible.

3. **Notification bell** — header icon with small count badge. Very quiet: only teach-me prompts, T3 approvals, and check-in prompts. Maybe 1-2 items per week. No template update confirmations, no agent activity, no routine plumbing.

4. **Learning history** — collapsed section on the template detail page. Opt-in curiosity, never pushed.

```
▸ Explore how your template has been learning    (3 updates)
```

Expands to:

```
▾ Explore how your template has been learning    (3 updates)

  Apr 10 — Added: always include Clinical Correlation in impression
           You added this in 7 of your last 10 reports
           [Undo]

  Apr 5  — Updated terminology: "filling defect" → "thrombus"
           You consistently made this substitution
           [Undo]

  Apr 2  — Adjusted: single-sentence impression for normal studies
           You simplified the impression in 4 of 5 normal cases
           [Undo]
```

Each entry: evidence quoted in the radiologist's own behaviour, [Undo] reverts to prior TemplateVersion. Past tense framing ("you added this" not "we changed your template"). The learning history is where trust gets built gradually and where repairs happen if something goes wrong.

### What the radiologist does NOT see

- Activity timeline / chronological agent log (backend audit surface only)
- Template update notifications (silent — discoverable via learning history)
- LEARN mode outcomes unless they surface as teach-me prompts
- Any T1/T2 autonomous action announcements
- Agent confidence scores, mode names, or implementation terminology

### The rule for SCHEMA.md

> **Silent by default.** Autonomous actions (T1, T2) produce no user-visible notification. The radiologist discovers them via the learning history when curious. Only items requiring input (teach-me prompts, T3 approvals, check-ins) surface as notifications. The goal is that template improvement feels organic and gradual, never abrupt or alarming. The learning should be felt, not seen.

## Integration with Existing Architecture

### Maintenance Agent — LEARN Mode

LEARN is a new mode added to the maintenance agent's system prompt (see `project_maintenance_agent.md`). Same inviolable rules, same tool set, same proposal output format.

**LEARN mode system prompt addition:**

```
LEARN — Runs on periodic lint schedule, NOT gated by user feedback.
  Reads accumulated report_feedback diffs for each template.
  Extracts consistent edit patterns.
  Proposes skill sheet refinement rules derived from human corrections.
  Evidence must be quoted directly from the diffs — never inferred or abstracted.
  The HUMAN EDIT is the signal, not the AI output.
  Check against: existing skill sheet rules, global style guide, rejection log.
  Pattern threshold: ≥60% of recent reports with edits, minimum 3 occurrences.
  Global patterns (same edit across 3+ templates): propose promoting to global
  style guide, not individual skill sheet updates.
```

**LEARN mode tools (additions):**

- `get_feedback(template_id, since?)` → accumulated report_feedback rows with diffs
- `get_template_rating(template_id, user_id)` → aggregate stats (positive/negative counts, avg edit distance, last check-in)
- `compute_section_diffs(template_id, since?)` → section-level diff summary across reports

### Skill Sheet Update Path

All feedback-driven updates flow through the existing `refine_skill_sheet` method (`template_manager.py:~3348`). The maintenance agent is just another caller:

```
LEARN mode detects pattern
    → proposes refinement rule (e.g. "Add rule: always include Clinical
      Correlation section in impression when clinical history mentions
      ongoing treatment")
    → if T3: notification bell → radiologist approves
    → if T2/T1: agent calls refine_skill_sheet directly
    → refine_skill_sheet(skill_sheet, proposed_rule) → updated skill sheet
    → create_template_version() → TemplateVersion row (reversible)
    → learning history entry created
```

No new update mechanism. No new refinement path. The existing refine endpoint, the existing version chain, the existing TemplateVersion snapshots — all reused.

### Version Chain and Reversibility

Every feedback-driven update creates a `TemplateVersion` row via the existing `crud.create_template_version()`. The learning history UI renders these versions filtered to agent-originated changes. [Undo] reverts to the prior version and records the revert as a calibration signal (demotes the pattern one autonomy tier).

## Iteration Plan Integration

The feedback pipeline weaves into the existing iteration plan at natural points:

**Iteration 4 (add to existing scope):**
- Create `report_feedback` table (schema above)
- Create `template_rating` table (schema above)
- Add browser `copy` event listener on report container (captures Cmd+C)
- Wire existing copy button handler to also capture feedback
- Add component unmount handler for abandoned detection
- Capture `ai_output` at generation time, `final_output` on copy, compute `edit_distance` and `sections_modified`
- Start accumulating data immediately — no analysis pipeline yet

**Iteration 6 (add to existing scope):**
- Post-copy thumbs up/down toast
- N-use check-in banner (5, 15, 30, exponential)
- Notification bell in header (teach-me prompts, T3 approvals, check-ins only)
- Learning history collapsed section on template detail page
- "Needs tweaking" → pre-loaded refine with LEARN findings

**Iteration 7 (add to existing scope):**
- LEARN mode for maintenance agent
- Periodic lint schedule running LEARN alongside VERIFY/RECONCILE/SUGGEST
- Pattern detection logic (≥60% consistency, ≥3 occurrences, dedup against existing rules)
- Teach-me prompt surfacing via notification bell
- Calibration log integration (LEARN proposals earn T3 → T2 → T1 per pattern)
- Global pattern detection (same edit across 3+ templates → propose global style guide promotion)

## Not In Scope

- Per-section inline feedback annotations (the diff IS the section-level signal)
- Regeneration from feedback (existing edit → copy flow is sufficient)
- Per-report assertion input (routes through teach-me when patterns accumulate)
- Real-time streaming of template updates (silent by design)
- Cross-user learning (per-user only; institutional aggregation is a future consideration)
- Automated A/B testing of skill sheet variants (possible future but not designed here)
