# Refine Verification Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user verify or reject each refine mutation atomically, with rejection driving a rollback + failure-context retry — so silent under/over-change becomes surfaceable instead of compounding.

**Architecture:** After each refine turn, the assistant message carries a `behavioral_claim` (already produced by the backend prompt) rendered as an inline verification banner with a `Not quite` action. A per-message `status` field (`pending` | `confirmed` | `rejected`) tracks turn outcome. On rejection the frontend rolls the skill sheet back to a pre-mutation snapshot captured before the turn, and the next user message is sent with `rejection_context` (original instruction + rejected claim + clarification) so the model re-plans from the right starting point. Rejected turns stay visible in amber as a compounding signal.

**Tech Stack:** Python / FastAPI / Pydantic (backend), Svelte 4 / Tailwind (frontend). Two frontend components implement the flow: `TemplateRefinePanel.svelte` (drawer on the templates page) and `SkillSheetCreator.svelte` (workbench refine stage).

---

## File Map

**Backend:**
- Modify `backend/src/rapid_reports_ai/template_manager.py` — `refine_skill_sheet` gains optional `rejection_context` parameter + prompt variant that includes failure context
- Modify `backend/src/rapid_reports_ai/main.py` — `SkillSheetRefineRequest` gains optional `rejection_context` field; `skill_sheet_refine_endpoint` forwards it

**Frontend — shared chat message type extended in two places:**
- Modify `frontend/src/routes/components/TemplateRefinePanel.svelte` — verification banner, rollback snapshot, rejection state, failure-context send
- Modify `frontend/src/routes/components/SkillSheetCreator.svelte` (refine stage, ~lines 810-870 + chat state) — same changes in the workbench flow

**No new files.** Both Svelte components already hold the chat state — the change is extending that state and rendering the banner inline.

---

## Task 1: Backend — add `rejection_context` to `refine_skill_sheet` + prompt variant

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_manager.py:3569-3688`

- [ ] **Step 1: Extend function signature**

In `template_manager.py`, change the `refine_skill_sheet` signature from:

```python
async def refine_skill_sheet(
    self,
    skill_sheet: str,
    message: str,
    chat_history: List[Dict[str, str]],
    api_key: str,
) -> Dict:
```

to:

```python
async def refine_skill_sheet(
    self,
    skill_sheet: str,
    message: str,
    chat_history: List[Dict[str, str]],
    api_key: str,
    rejection_context: Optional[Dict[str, str]] = None,
) -> Dict:
```

Make sure `Optional` and `Dict` are imported at the top of the file (they should already be — verify).

- [ ] **Step 2: Update docstring**

Replace the existing docstring inside `refine_skill_sheet` with:

```python
"""
Refine a skill sheet based on radiologist feedback via chat.

Args:
    skill_sheet: Current skill sheet markdown (post-rollback if this turn follows a rejection)
    message: Radiologist's latest message
    chat_history: Previous turns as [{"role": "user"|"assistant", "content": str}]
    api_key: Cerebras API key
    rejection_context: Optional failure context when this turn follows a rejected refine.
        Shape: {
            "original_instruction": str,   # what the user originally asked for
            "rejected_claim": str,          # behavioral_claim the model produced and user rejected
        }
        When present, the prompt tells the model its previous mutation was rejected and
        must re-plan from the pre-mutation skill sheet using the clarification in `message`.

Returns:
    { skill_sheet: str, response: str, behavioral_claim: str }
"""
```

- [ ] **Step 3: Build the failure-context user-prompt variant**

Replace the current `user_prompt = f"""...` block (lines ~3641-3661) with:

```python
if rejection_context:
    failure_block = f"""
=== PREVIOUS ATTEMPT WAS REJECTED ===
The radiologist previously asked: "{rejection_context.get('original_instruction', '').strip()}"
You produced this claim: "{rejection_context.get('rejected_claim', '').strip()}"
The radiologist rejected it — the behaviour did not match what they wanted.

The skill sheet above has been rolled back to its state before that rejected attempt.
Treat the message below as a clarification of what they actually meant. Re-plan from scratch using both the original instruction and the clarification together — do not repeat the rejected mutation.
"""
else:
    failure_block = ""

user_prompt = f"""Current Skill Sheet:
```markdown
{skill_sheet}
```
{history_section}{failure_block}

=== RADIOLOGIST'S MESSAGE ===
{message}

Before producing the output, reason through these steps internally:
1. What specific behavioural outcome does this instruction require? State it as a sentence describing what a future generated report should look like.
2. Which rules in the current skill sheet already produce this behaviour? Cite them specifically.
3. Which rules conditionally prevent, qualify, or would counteract this behaviour? Cite them specifically — these must be removed or modified, not just worked around.
4. What new rules are needed, if any?
5. Consolidate into a single coherent mutation and produce the full updated skill sheet.

Then return a JSON object with all three fields:
- "skill_sheet": the complete updated document with ALL necessary changes (additions, modifications, and removals)
- "response": conversational confirmation in behavioural/clinical language (1-2 sentences, no internal structure references)
- "behavioral_claim": specific falsifiable assertion in the format "[observable thing] should now [observable state]"
"""
```

Note the `{failure_block}` is inserted between `{history_section}` and the radiologist's message — it separates "what happened before" from "what they're saying now".

- [ ] **Step 4: Manual smoke test**

Start the backend and call the refine endpoint twice — first normally, then with a crafted rejection_context — verify the second call's user_prompt contains the `=== PREVIOUS ATTEMPT WAS REJECTED ===` block by reading the logged prompt. (The endpoint logs `skill_sheet in` and `message` already; temporarily add `logger.info("  user_prompt: %s", user_prompt)` in `refine_skill_sheet` if needed to confirm, then remove.)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_manager.py
git commit -m "feat(refine): rejection_context param re-plans from pre-mutation state"
```

---

## Task 2: Backend — endpoint accepts + forwards `rejection_context`

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py:688-695` (request model)
- Modify: `backend/src/rapid_reports_ai/main.py:2303-2337` (endpoint)

- [ ] **Step 1: Extend `SkillSheetRefineRequest`**

Change:

```python
class SkillSheetRefineRequest(BaseModel):
    skill_sheet: str
    message: str
    chat_history: Optional[List[SkillSheetChatMessage]] = None
```

to:

```python
class SkillSheetRejectionContext(BaseModel):
    original_instruction: str
    rejected_claim: str

class SkillSheetRefineRequest(BaseModel):
    skill_sheet: str
    message: str
    chat_history: Optional[List[SkillSheetChatMessage]] = None
    rejection_context: Optional[SkillSheetRejectionContext] = None
```

- [ ] **Step 2: Forward into `refine_skill_sheet`**

In `skill_sheet_refine_endpoint`, change the call from:

```python
result = await tm.refine_skill_sheet(
    skill_sheet=request.skill_sheet,
    message=request.message,
    chat_history=history,
    api_key=api_key,
)
```

to:

```python
rejection_ctx = (
    {"original_instruction": request.rejection_context.original_instruction,
     "rejected_claim": request.rejection_context.rejected_claim}
    if request.rejection_context else None
)
result = await tm.refine_skill_sheet(
    skill_sheet=request.skill_sheet,
    message=request.message,
    chat_history=history,
    api_key=api_key,
    rejection_context=rejection_ctx,
)
```

- [ ] **Step 3: Log rejection context arrival**

Just below the existing `logger.info("  chat_history: %d turns", ...)` line add:

```python
if request.rejection_context:
    logger.info("  rejection_context: rejected_claim=%r", request.rejection_context.rejected_claim[:200])
```

- [ ] **Step 4: Restart backend + manual check**

Start the dev backend (`make backend-dev` or equivalent). From a terminal:

```bash
curl -X POST http://localhost:8000/api/templates/skill-sheet/refine \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"skill_sheet":"# Tiny\nRule 1","message":"try again","chat_history":[],"rejection_context":{"original_instruction":"always X","rejected_claim":"X should now appear"}}'
```

Expected: 200 response with `skill_sheet`, `response`, `behavioral_claim`; backend log shows the new `rejection_context:` line.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py
git commit -m "feat(refine): endpoint forwards rejection_context to template_manager"
```

---

## Task 3: Frontend — extend chat-message model in `TemplateRefinePanel.svelte`

**Files:**
- Modify: `frontend/src/routes/components/TemplateRefinePanel.svelte:12-68` (state + sendMessage + saveChanges)

Chat messages currently carry only `{role, content}`. We need to carry per-turn metadata: the `behavioral_claim` from the backend, a `status` (`'pending' | 'confirmed' | 'rejected'`), the pre-mutation skill sheet snapshot (so rejection rolls back), and the original user instruction that led to this assistant turn.

**State-model rules:**
- Frontend-only fields (`behavioralClaim`, `preMutationSkillSheet`, `originalInstruction`, `status`) MUST be stripped before sending `chat_history` to the backend. Sending them through either errors the Pydantic validator or — if it tolerates extras — feeds garbage into the prompt. This risk is the reason we extract a named helper rather than using an inline `.map()`.
- `status === 'pending'` means the behavioral claim is live. Saving the template is itself a confirmation: `saveChanges` flips every `pending` → `confirmed` before the PUT. A turn that reached save is verified by having survived that long.
- The index-0 case in `rejectTurn` (no preceding user message) is guarded explicitly — even though conversation flow never produces it today, a future refactor could.

- [ ] **Step 1: Add a wire-sanitiser helper at the top of the `<script>` block**

Immediately after the `const dispatch = createEventDispatcher();` line, add:

```javascript
/**
 * Strip frontend-only fields before sending chat history to the backend.
 * The backend Pydantic model (SkillSheetChatMessage) only accepts {role, content}.
 * Any extra fields (behavioralClaim, preMutationSkillSheet, originalInstruction, status)
 * would either 422 or leak into the LLM prompt.
 */
function toWireChatHistory(history) {
    return history
        .filter(m => m && (m.role === 'user' || m.role === 'assistant'))
        .map(({ role, content }) => ({ role, content }));
}
```

- [ ] **Step 2: Extend sendMessage to capture pre-mutation snapshot + store metadata on the assistant message**

Replace the current `sendMessage` function (lines 43-68) with:

```javascript
async function sendMessage() {
    if (!chatInput.trim() || !skillSheet || loading) return;
    const msg = chatInput.trim();
    chatInput = '';

    // Snapshot the current skill sheet BEFORE the mutation — used for rollback
    const preMutationSkillSheet = skillSheet;

    // If the prior assistant turn is rejected, build rejection_context from it
    const lastAssistant = [...chatHistory].reverse().find(m => m.role === 'assistant');
    const rejectionContext = (lastAssistant && lastAssistant.status === 'rejected')
        ? {
            original_instruction: lastAssistant.originalInstruction || '',
            rejected_claim: lastAssistant.behavioralClaim || '',
          }
        : null;

    chatHistory = [...chatHistory, { role: 'user', content: msg, status: null }];
    loading = true;
    error = '';

    try {
        const data = await postJson('/api/templates/skill-sheet/refine', {
            skill_sheet: skillSheet,
            message: msg,
            chat_history: toWireChatHistory(chatHistory.slice(0, -1)),
            rejection_context: rejectionContext
        });
        if (!data.success) throw new Error(data.error);
        skillSheet = data.skill_sheet;
        chatHistory = [...chatHistory, {
            role: 'assistant',
            content: data.response,
            behavioralClaim: data.behavioral_claim || '',
            preMutationSkillSheet,
            originalInstruction: msg,
            status: 'pending',
        }];
        hasChanges = true;
    } catch (e) {
        error = e instanceof Error ? e.message : String(e);
        chatHistory = chatHistory.slice(0, -1);
    } finally {
        loading = false;
    }
}
```

Note: `chat_history` is passed through `toWireChatHistory` — the one place this helper must be used on this path.

- [ ] **Step 3: Add a rollback helper with explicit index-0 guard**

Just above `sendMessage`, add:

```javascript
function rejectTurn(assistantIndex) {
    const target = chatHistory[assistantIndex];
    if (!target || target.role !== 'assistant') return;

    // Roll skill sheet back to state before this turn
    if (typeof target.preMutationSkillSheet === 'string') {
        skillSheet = target.preMutationSkillSheet;
    }

    // Mark this turn as rejected; also mark the triggering user turn if present.
    // Index-0 case (no preceding user message) shouldn't happen in the current
    // flow since assistants only reply to users — guarded here defensively.
    const updated = [...chatHistory];
    updated[assistantIndex] = { ...target, status: 'rejected' };
    const userIndex = assistantIndex - 1;
    if (userIndex >= 0 && updated[userIndex]?.role === 'user') {
        updated[userIndex] = { ...updated[userIndex], status: 'rejected' };
    }
    chatHistory = updated;

    hasChanges = skillSheet !== (template?.template_config?.skill_sheet || '');
}
```

- [ ] **Step 4: Flip pending → confirmed on save**

Inside `saveChanges`, just before the existing `const updatedConfig = { ... }` line, add:

```javascript
// Saving is itself a confirmation of every still-pending turn.
chatHistory = chatHistory.map(m =>
    m.status === 'pending' ? { ...m, status: 'confirmed' } : m
);
```

This has no backend effect (the chat history isn't persisted), but makes the UI state semantically correct: pending banners vanish at save time in any code path that keeps the drawer open.

- [ ] **Step 5: Manual type check**

Svelte 4 is JS, not TS — no compiler check. Start the frontend (`pnpm dev` or `npm run dev` per repo conventions) and open the templates page → open a template → open refine drawer. Confirm:
1. Existing behaviour still works (send a message, response renders).
2. Open devtools Network tab → inspect the `/skill-sheet/refine` request body → confirm `chat_history` entries contain ONLY `role` + `content` (no `behavioralClaim`, `preMutationSkillSheet`, etc). This is the critical check for the sanitiser.
3. No console errors on chat send.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/components/TemplateRefinePanel.svelte
git commit -m "refactor(refine-panel): capture pre-mutation snapshot + per-turn metadata"
```

---

## Task 4: Frontend — verification banner + `Not quite` button in `TemplateRefinePanel.svelte`

**Files:**
- Modify: `frontend/src/routes/components/TemplateRefinePanel.svelte:190-199` (message render block)

- [ ] **Step 1: Replace the message render loop with status-aware rendering**

Find the block:

```svelte
{#each chatHistory as msg}
    <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
        <div class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm
            {msg.role === 'user'
                ? 'bg-purple-600/20 border border-purple-500/20 text-purple-100'
                : 'bg-white/[0.04] border border-white/[0.06] text-gray-300'}">
            {msg.content}
        </div>
    </div>
{/each}
```

Replace with:

```svelte
{#each chatHistory as msg, i}
    <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
        <div class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm
            {msg.role === 'user'
                ? (msg.status === 'rejected'
                    ? 'bg-amber-500/10 border border-amber-500/40 text-amber-100'
                    : 'bg-purple-600/20 border border-purple-500/20 text-purple-100')
                : (msg.status === 'rejected'
                    ? 'bg-amber-500/10 border border-amber-500/40 text-amber-100'
                    : 'bg-white/[0.04] border border-white/[0.06] text-gray-300')}">
            {msg.content}
        </div>
    </div>
    {#if msg.role === 'assistant' && msg.behavioralClaim && msg.status === 'pending'}
        <div class="flex justify-start">
            <div class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-xs bg-purple-500/5 border border-purple-500/20 text-purple-200/90 space-y-2">
                <p class="leading-snug">{msg.behavioralClaim} — does this look right?</p>
                <div class="flex gap-2">
                    <button
                        class="px-2.5 py-1 rounded-md bg-white/[0.04] hover:bg-amber-500/15 border border-white/10 hover:border-amber-500/40 text-gray-400 hover:text-amber-200 transition-colors"
                        on:click={() => rejectTurn(i)}>
                        Not quite
                    </button>
                </div>
            </div>
        </div>
    {/if}
{/each}
```

- [ ] **Step 2: Manual UX check**

Open refine drawer on an existing template. Send: `"always include clinical correlation"`. Expected:
1. Assistant reply renders.
2. Below it a small purple-tinted banner shows the behavioral_claim with `— does this look right?` and a `Not quite` button.
3. Click `Not quite`. Expected: skill sheet reverts (check by re-opening — but easier check: send a different refine message and confirm it's based on the pre-rejected text). The user message and assistant message gain the amber border. Banner disappears (status is no longer `'pending'`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/components/TemplateRefinePanel.svelte
git commit -m "feat(refine-panel): behavioral_claim verification banner + Not quite"
```

---

## Task 5: Frontend — mirror changes in `SkillSheetCreator.svelte` refine stage

`SkillSheetCreator.svelte` has its own chat state and a `sendAnswer(text)` function that hits the same refine endpoint. The three changes from Tasks 3 + 4 need to land here too so the workbench flow is consistent.

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte` (refine stage around lines 810-870 + wherever `sendAnswer` and chat state live)

- [ ] **Step 1: Locate the refine-send path and chat state**

Run:

```bash
grep -n "sendAnswer\|chatHistory\|/api/templates/skill-sheet/refine" frontend/src/routes/components/SkillSheetCreator.svelte
```

Note the line numbers for: chat state declaration (likely near top with the other `let` declarations), `sendAnswer` function, the refine endpoint call, and the `{#each chatHistory ...}` render in the refine stage.

- [ ] **Step 2: Copy the `toWireChatHistory` helper into this component's `<script>`**

Paste the same helper from Task 3 Step 1 — identical code. This is the critical de-risking step: without it the `.map(({role, content}) => ...)` pattern is easy to forget in one of the two call sites, which fails silently (backend receives junk fields).

If `SkillSheetCreator.svelte`'s chat state mixes in non-refine entries (e.g., from the `questions` stage), the helper's `filter` naturally drops anything without `role` in `{user, assistant}`. The name and filter keep that invariant visible.

- [ ] **Step 3: Apply the same pre-mutation snapshot + metadata capture in `sendAnswer`**

Using the pattern from Task 3 Step 2, modify `sendAnswer` (or equivalent) to:
1. Capture `preMutationSkillSheet = skillSheet` before the POST.
2. Build `rejectionContext` from the last `assistant` message whose `status === 'rejected'`.
3. POST via `toWireChatHistory(chatHistory)` + `rejection_context`.
4. Push the assistant message with `{behavioralClaim, preMutationSkillSheet, originalInstruction, status: 'pending'}`.

If `SkillSheetCreator.svelte`'s chat state may mix non-refine entries, scope the rejection-context lookup and metadata stamping to refine-stage entries only — the refine stage sets messages only while `stage === 'refine'`.

- [ ] **Step 4: Add the same `rejectTurn(index)` helper with the index-0 guard**

Copy the helper from Task 3 Step 3 verbatim. The `hasChanges` recomputation may need adapting to what this component tracks — if it uses a different dirty-flag name (`hasGenerated`, `isDirty`, etc.), adjust accordingly. If no such flag exists in this component, just drop the `hasChanges` line.

- [ ] **Step 5: Flip pending → confirmed wherever this component's "save/finalise" path lives**

Find the function in `SkillSheetCreator.svelte` that finalises/saves the skill sheet (likely tied to the "Save" or "Done" action after the refine stage). Just before the PUT/save call, add:

```javascript
chatHistory = chatHistory.map(m =>
    m.status === 'pending' ? { ...m, status: 'confirmed' } : m
);
```

Same semantic as TemplateRefinePanel — save confirms all still-pending turns.

- [ ] **Step 6: Update the refine-stage chat render block (lines 828-836)**

Find:

```svelte
{#each chatHistory as msg}
    {#if msg.role === 'user'}
        <div class="flex justify-end">
            <div class="max-w-[90%] bg-purple-600/20 border border-purple-500/15 rounded-2xl rounded-br-sm px-4 py-2.5 text-sm text-gray-200" style="white-space: pre-wrap;">{msg.content}</div>
        </div>
    {:else}
        <div class="max-w-[90%] bg-white/[0.03] border border-white/10 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-300 leading-relaxed" style="white-space: pre-wrap;">{msg.content}</div>
    {/if}
{/each}
```

Replace with:

```svelte
{#each chatHistory as msg, i}
    {#if msg.role === 'user'}
        <div class="flex justify-end">
            <div class="max-w-[90%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm {msg.status === 'rejected' ? 'bg-amber-500/10 border border-amber-500/40 text-amber-100' : 'bg-purple-600/20 border border-purple-500/15 text-gray-200'}" style="white-space: pre-wrap;">{msg.content}</div>
        </div>
    {:else}
        <div class="max-w-[90%] rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm leading-relaxed {msg.status === 'rejected' ? 'bg-amber-500/10 border border-amber-500/40 text-amber-100' : 'bg-white/[0.03] border border-white/10 text-gray-300'}" style="white-space: pre-wrap;">{msg.content}</div>
        {#if msg.behavioralClaim && msg.status === 'pending'}
            <div class="max-w-[90%] mt-1.5 rounded-xl px-3.5 py-2.5 text-xs bg-purple-500/5 border border-purple-500/20 text-purple-200/90 space-y-2">
                <p class="leading-snug">{msg.behavioralClaim} — does this look right?</p>
                <div class="flex gap-2">
                    <button
                        class="px-2.5 py-1 rounded-md bg-white/[0.04] hover:bg-amber-500/15 border border-white/10 hover:border-amber-500/40 text-gray-400 hover:text-amber-200 transition-colors"
                        on:click={() => rejectTurn(i)}>
                        Not quite
                    </button>
                </div>
            </div>
        {/if}
    {/if}
{/each}
```

- [ ] **Step 7: Manual UX check in workbench flow**

Start `pnpm dev` if not running. From the workbench, create a new skill sheet → generate → refine stage → send a refine message. Also confirm via devtools Network tab that `chat_history` entries only contain `role` + `content`. Expected behaviour otherwise identical to Task 4 Step 2.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte
git commit -m "feat(skill-sheet-creator): verification banner + Not quite in refine stage"
```

---

## Task 6: End-to-end validation

Goal: exercise the full loop in a real browser against a real backend to confirm the atomic transaction + failure-context retry works as specified.

- [ ] **Step 1: Pick a controlled test template**

Use the local copy of Sabeeh's CTCA template already in the Hassan sandbox account (template id `bc2ebcf7-6298-47dc-a2ba-de2152f61258` per prior session).

- [ ] **Step 2: Scenario A — reject then clarify**

1. Open refine drawer on the CTCA template.
2. Send: `"use 'severe' not 'severe stenosis (70-99%)'"`.
3. When the banner renders, click `Not quite`.
4. Confirm the amber border appears on both messages and the banner disappears.
5. Send a clarification: `"I meant only in the impression section, keep the parenthetical grading in the report body"`.
6. Backend log should show `rejection_context:` line with the previously-rejected claim.
7. The new assistant response should NOT repeat the overbroad terminology change.

- [ ] **Step 3: Scenario B — confirm-by-not-rejecting**

1. Send another refine: `"always include heart rate variability when available"`.
2. Read the behavioral_claim — if correct, simply proceed (do nothing). The turn stays `pending` until either another message is sent or the drawer is closed. This is the "behavioral assertion with implicit invitation to falsify" pattern: absence of rejection == acceptance.
3. Close the drawer with `Save`. Expected: changes persist, template reloads with updated skill sheet.

- [ ] **Step 4: Record observed behaviour**

Note in a scratch comment for the session: did the rollback actually revert the skill sheet? Did the failure-context prompt produce a meaningfully different retry? If either fails, open an issue-style comment in the plan doc before proceeding to commit-merge.

- [ ] **Step 5: Final commit (if amendments needed from validation, otherwise skip)**

If validation surfaced small regressions (typos, missing edge-case guards), fix inline and commit as `fix(refine): <specific thing>`. Do not bundle unrelated changes.

---

## Out of Scope (deliberately deferred)

- **"Test your change" button in `TemplateRefinePanel.svelte`:** requires on-demand sample-findings generation (no sample findings exist in that component's state). Separate plan.
- **Inline skill-sheet diff view after each turn:** would make the verification more concrete but is a larger UX shift.
- **Auto-confirm after successful `test-generate`:** currently only rejection has a button; confirmation is implicit. Revisit after real usage.
- **Compounding learning signal beyond amber styling:** the rejected messages are visible in history but not yet fed into subsequent unrelated turns. Fine for now.

---

## Self-Review Notes

- Spec coverage: banner ✓, status field ✓, amber styling ✓, pre-mutation snapshot ✓, rollback on Not quite ✓, failure-context retry ✓, save-as-implicit-confirm ✓. "Test your change" explicitly deferred.
- Type consistency: frontend property names (`behavioralClaim`, `preMutationSkillSheet`, `originalInstruction`, `status`) used consistently across Tasks 3–5. Backend key names are `snake_case` (`behavioral_claim`, `rejection_context.original_instruction`, `rejection_context.rejected_claim`) consistently.
- `toWireChatHistory` is a named helper (not inline `.map()`) to eliminate the silent-bug risk of forgetting to strip frontend-only fields when mirroring Task 3 into Task 5.
- `rejectTurn` guards index-0 explicitly even though conversation flow should never produce it.
- Pending turns are flipped to `'confirmed'` on save in both components — the "saving is a confirmation" semantic.
- Execution order: Task 4 manual UX check MUST pass before touching Task 5 so the mirror starts from a known-working reference.
- No TBDs or placeholders. Each code step has the actual code.
- Testing: pragmatically manual (no existing refine-flow tests to slot into), called out in Task 6.
