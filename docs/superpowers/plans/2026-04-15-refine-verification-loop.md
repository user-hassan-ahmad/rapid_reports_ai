# Refine Verification Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user verify or reject each refine mutation atomically, with rejection driving a rollback + failure-context retry — so silent under/over-change becomes surfaceable instead of compounding.

**Architecture:** After each refine turn, the assistant message carries a `behavioral_claim` (already produced by the backend prompt) rendered as an inline verification banner with a `Not quite` action. A per-message `status` field (`pending` | `confirmed` | `rejected`) tracks turn outcome. On rejection the frontend rolls the skill sheet back to a pre-mutation snapshot captured before the turn, and the next user message is sent with `rejection_context` (original instruction + rejected claim + clarification) so the model re-plans from the right starting point. Rejected turns stay visible in amber as a compounding signal.

**Tech Stack:** Python / FastAPI / Pydantic (backend), Svelte 4 / Tailwind (frontend). The verification loop lives in `SkillSheetCreator.svelte` (workbench refine stage) only. `TemplateRefinePanel.svelte` (production drawer) keeps its existing confirm-and-save UX — see Scope Pivot below.

---

## Scope Pivot — 2026-04-15 (mid-execution)

Original plan placed the verification loop in both `TemplateRefinePanel.svelte` (drawer) and `SkillSheetCreator.svelte` (workbench). On live testing, the drawer was the wrong home for it:

- The drawer overlays the active report editor. A user refining their template may have manual edits to the current report, or may just be updating a preference for *future* reports — forcing a regenerate-to-verify cycle there is destructive.
- There's no in-panel surface to test the behavioral_claim against (no sample findings in scope, no side-by-side preview) — so `Not quite` becomes an obligation the UI can't actually support.
- The correct audit layer for the drawer is the existing `TemplateVersion` chain (visible via VersionHistory tab): per-save granularity, reversible. That matches the drawer's "preference update" mental model.

**Decision:**

- **Workbench (`SkillSheetCreator.svelte`)** → full verification loop: banner, `Not quite`, rollback, failure-context retry. The workbench already has `sampleFindings`, a side-by-side `Regenerate` surface, and compare mode — verification is naturally supported.
- **Production drawer (`TemplateRefinePanel.svelte`)** → reverts to its pre-plan UX. Only the `toWireChatHistory` helper is retained (harmless defensive code).
- **Backend (Tasks 1 + 2)** → stays as-is. `rejection_context` is Optional on the Pydantic model and a no-op when None, so the drawer sends nothing and gets identical behaviour to before.

Tasks 3 and 4 in this document describe the drawer work that was done and then reverted — preserved for history. Task 3R below undoes them surgically. Task 5 is the full workbench implementation. Task 6 scenarios now run in the workbench flow.

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

## Task 3R: Revert the drawer — keep only `toWireChatHistory`

**Scope pivot 2026-04-15:** Tasks 3 and 4 were executed (commits `abc7cf7` and `2317a24`) and then reverted per the Scope Pivot section above. This task is the revert itself.

**Files:**
- Modify: `frontend/src/routes/components/TemplateRefinePanel.svelte`

- [ ] **Step 1: Remove the banner + Not quite render block**

Restore the original `{#each chatHistory as msg}` block — no `, i` index, no `behavioralClaim` branch, no amber-variant classes.

- [ ] **Step 2: Remove `rejectTurn` function entirely**

- [ ] **Step 3: Revert `sendMessage` to its simple shape**

Keep `toWireChatHistory(...)` in the call (harmless defensive code). Drop `preMutationSkillSheet`, `rejectionContext` lookup, and the metadata on the assistant message push.

- [ ] **Step 4: Revert the `saveChanges` pending→confirmed flip**

There's no `status` to flip anymore.

- [ ] **Step 5: Keep `toWireChatHistory`**

The helper stays at the top of the `<script>` block. It's idempotent with the original inline `.map()` behaviour and de-risks future callers.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/components/TemplateRefinePanel.svelte
git commit -m "revert(refine-panel): verification loop lives in workbench, not drawer"
```

---

## Task 3 [SUPERSEDED by Task 3R]: Frontend — extend chat-message model in `TemplateRefinePanel.svelte`

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

## Task 4 [SUPERSEDED by Task 3R]: Frontend — verification banner + `Not quite` button in `TemplateRefinePanel.svelte`

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

## Task 5: Frontend — verification loop in `SkillSheetCreator.svelte` (workbench)

After the scope pivot this task is the full home of the verification loop: helper + chat-message metadata + banner + `Not quite` rollback + failure-context retry + save-confirms.

**Workbench specifics that differ from the drawer:**
- `chatHistory` is shared between the **questions** stage (Q&A during analyze) and the **refine** stage (post-generation). Messages from the questions stage should NOT trigger banners. The natural filter is `msg.behavioralClaim && msg.status === 'pending'` — messages from the questions stage won't have `behavioralClaim` so they fall through silently.
- Metadata is attached inside `sendAnswer` only when `stage === 'refine'` — keeps questions-stage entries clean.
- The workbench's "save" is `saveAsTemplate` (line ~421) — that's where pending turns flip to confirmed.
- The workbench has native verification surfaces: `testFindings` + `runTestGenerate` + side-by-side `Report preview` + `Compare` mode with `prevReport`. Verification pressure is natural here.

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte` — chat state (~line 64), `sendAnswer` (~line 334), `saveAsTemplate` (~line 421), refine-stage render block (~lines 828-836)

- [ ] **Step 1: Add `toWireChatHistory` helper near the top of the `<script>` block**

```javascript
function toWireChatHistory(history) {
    return history
        .filter((m) => m && (m.role === 'user' || m.role === 'assistant'))
        .map(({ role, content }) => ({ role, content }));
}
```

- [ ] **Step 2: Add the `rejectTurn` helper above `sendAnswer`**

```javascript
function rejectTurn(assistantIndex) {
    const target = chatHistory[assistantIndex];
    if (!target || target.role !== 'assistant') return;

    if (typeof target.preMutationSkillSheet === 'string') {
        skillSheet = target.preMutationSkillSheet;
    }

    const updated = [...chatHistory];
    updated[assistantIndex] = { ...target, status: 'rejected' };
    const userIndex = assistantIndex - 1;
    if (userIndex >= 0 && updated[userIndex]?.role === 'user') {
        updated[userIndex] = { ...updated[userIndex], status: 'rejected' };
    }
    chatHistory = updated;
}
```

Note: no `hasChanges` flag in this component — the skill sheet itself is the state; the side-by-side preview updates via `runTestGenerate`.

- [ ] **Step 3: Extend `sendAnswer` with pre-mutation snapshot + refine-stage metadata**

Replace the existing `sendAnswer` (lines 334-361) with:

```javascript
async function sendAnswer(/** @type {string} */ msg) {
    if (!msg.trim() || !skillSheet) return;
    chatInput = '';
    let fullMsg = msg;

    if (activeQuestionIdx >= 0 && questions[activeQuestionIdx]) {
        const q = questions[activeQuestionIdx];
        fullMsg = `Q: ${q.question}\nA: ${msg}`;
        questions[activeQuestionIdx] = { ...q, status: 'answered', answer: msg };
        questions = questions;
        activeQuestionIdx = -1;
    }

    // Verification-loop metadata only applies in the refine stage.
    const isRefineTurn = stage === 'refine';
    const preMutationSkillSheet = isRefineTurn ? skillSheet : null;

    const lastAssistant = isRefineTurn
        ? [...chatHistory].reverse().find((m) => m.role === 'assistant')
        : null;
    const rejectionContext =
        lastAssistant && lastAssistant.status === 'rejected'
            ? {
                    original_instruction: lastAssistant.originalInstruction || '',
                    rejected_claim: lastAssistant.behavioralClaim || ''
              }
            : null;

    chatHistory = [...chatHistory, { role: 'user', content: msg, status: isRefineTurn ? null : undefined }];
    loading = true;
    error = '';
    try {
        const data = await postJson('/api/templates/skill-sheet/refine', {
            skill_sheet: skillSheet,
            message: fullMsg,
            chat_history: toWireChatHistory(chatHistory.slice(0, -1)),
            rejection_context: rejectionContext
        });
        if (!data.success) throw new Error(data.error);
        skillSheet = data.skill_sheet;
        const assistantMsg = isRefineTurn
            ? {
                    role: 'assistant',
                    content: data.response,
                    behavioralClaim: data.behavioral_claim || '',
                    preMutationSkillSheet,
                    originalInstruction: msg,
                    status: 'pending'
              }
            : { role: 'assistant', content: data.response };
        chatHistory = [...chatHistory, assistantMsg];
    } catch (e) {
        error = e instanceof Error ? e.message : String(e);
        chatHistory = chatHistory.slice(0, -1);
    } finally {
        loading = false;
    }
}
```

- [ ] **Step 4: Flip pending → confirmed in `saveAsTemplate`**

Inside `saveAsTemplate` (line ~421), just before the `postJson('/api/templates/skill-sheet/save', ...)` call, add:

```javascript
chatHistory = chatHistory.map((m) =>
    m.status === 'pending' ? { ...m, status: 'confirmed' } : m
);
```

- [ ] **Step 5: Update the refine-stage chat render block (lines ~828-836)**

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

- [ ] **Step 6: Manual UX check in workbench flow**

Start `pnpm dev` if not running. From the workbench, Phase 1 (paste reports) → Phase 2 (analyze + answer questions) → test-generate → refine stage → send a refine message. Expected:
1. Assistant reply renders plus verification banner with `{behavioralClaim} — does this look right?` and `Not quite`.
2. Click `Not quite`: skill sheet reverts, both messages get amber border, banner disappears.
3. DevTools Network tab: `chat_history` entries contain ONLY `role` + `content`.
4. Questions-stage messages from earlier (Q&A during analyze) should NOT show banners — their `behavioralClaim` is undefined.
5. On Save (`saveAsTemplate`), any still-pending turns' banners should vanish (flipped to confirmed) before the request fires.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte
git commit -m "feat(skill-sheet-creator): verification banner + Not quite in refine stage"
```

---

## Task 6: End-to-end validation

Goal: exercise the full loop in a real browser against a real backend to confirm the atomic transaction + failure-context retry works as specified.

- [ ] **Step 1: Set up a workbench session**

Start a fresh workbench flow: Create from examples → paste 3 CT KUB reports → scan type "CT KUB" → analyze → answer or skip questions → test-generate. Land in the refine stage.

- [ ] **Step 2: Scenario A — clean mutation, accept by not rejecting**

1. From the refine stage, send: `"Always state perinephric stranding status explicitly in every report — present or absent, and describe the extent. Never omit it, even on completely normal studies."`
2. Verification banner appears. Click `Regenerate` to re-run the test-generate with the updated skill sheet. The previous vs current report shows in compare mode. Confirm perinephric stranding is now present.
3. Don't click `Not quite` — absence of rejection == acceptance. Banner stays pending until save.

- [ ] **Step 3: Scenario B — ambiguous, reject, clarify**

1. Send: `"Tighten up the report length."`
2. Banner renders with some interpretation (likely verbosity-stripping). Click `Not quite`.
3. Confirm amber border on both messages, skill sheet reverts, banner disappears.
4. Send: `"I meant specifically — when a coronary segment is normal, just list it under a 'normal segments' line rather than describing each one individually."`
5. Backend log should show `rejection_context: rejected_claim=...` with the tightening claim.
6. New banner should describe the grouping convention, not a repeat of generic tightening.

- [ ] **Step 4: Save and verify audit**

Click Save (`saveAsTemplate`). Expected:
1. Any remaining pending turns flip to confirmed before the request fires.
2. Template appears in the templates list with all accepted mutations but not the rejected one.
3. `TemplateVersion` row created (backend audit layer).

- [ ] **Step 4: Record observed behaviour**

Note in a scratch comment for the session: did the rollback actually revert the skill sheet? Did the failure-context prompt produce a meaningfully different retry? If either fails, open an issue-style comment in the plan doc before proceeding to commit-merge.

- [ ] **Step 5: Final commit (if amendments needed from validation, otherwise skip)**

If validation surfaced small regressions (typos, missing edge-case guards), fix inline and commit as `fix(refine): <specific thing>`. Do not bundle unrelated changes.

---

## Out of Scope (deliberately deferred)

- **Verification loop in the production drawer (`TemplateRefinePanel.svelte`):** per Scope Pivot, doesn't fit the drawer's mental model. Audit there lives via `TemplateVersion` + VersionHistory tab.
- **`change_note` on `TemplateVersion`:** chat history isn't persisted across sessions (frontend-only state; reset on drawer close / component mount). If per-save refinement *intent* becomes useful for audit later, add an optional `change_note: str` column to `TemplateVersion` — auto-populated from the first user message of the refine session, or user-typed at save time.
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
