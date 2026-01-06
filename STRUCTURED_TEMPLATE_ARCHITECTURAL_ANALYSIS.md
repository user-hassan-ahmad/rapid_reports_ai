# Structured Fill-In Template Architecture: Comprehensive Analysis

## Executive Summary

Your structured template system is well-architected for high-fidelity, subspecialty reporting. However, there are key areas requiring refinement around **placeholder semantics**, **blank section handling**, and **symbol clarity**. This analysis evaluates your current implementation and provides recommendations for optimization.

---

## 1. Current Architecture Overview

### 1.1 Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 1: Template Creation (Wizard - Step 4)                       │
├─────────────────────────────────────────────────────────────────────┤
│ User selects "Structured Fill-In Template" style                    │
│  └─> Defines template with placeholders:                           │
│       • xxx (measurements)                                          │
│       • ~VAR~ (variables)                                           │
│       • [a/b] (alternatives/conditionals)                          │
│  └─> Optional: AI generates template structure                     │
│  └─> Validation: Real-time syntax checking                         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 2: Report Generation                                         │
├─────────────────────────────────────────────────────────────────────┤
│ User provides dictated findings input                               │
│  └─> Backend prompt construction (template_manager.py:2123-2177)   │
│       • "STRICT FIDELITY REQUIRED" prompt                          │
│       • Template preservation with placeholder filling              │
│  └─> AI fills placeholders based on input:                         │
│       1. ~VAR~ → Replaced with measurements/values                 │
│       2. [text] → Conditional inclusion or alternative selection   │
│       3. xxx → Replaced with measurements or estimates             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 3: Post-Generation Detection & Editing                       │
├─────────────────────────────────────────────────────────────────────┤
│ Frontend placeholder detection (placeholderDetection.ts)            │
│  └─> Scans generated report for:                                   │
│       • Unfilled measurements (xxx)                                │
│       • Unfilled variables (~VAR~)                                 │
│       • Unresolved alternatives (a/b)                              │
│       • Remaining instructions [text]                              │
│  └─> Highlights unfilled items with hover actions                  │
│  └─> Allows quick-fill via UI popup                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Files & Responsibilities

| Component | File | Responsibility |
|-----------|------|---------------|
| **Template Creation** | `frontend/src/routes/components/wizard/Step4_FindingsSetup.svelte` | UI for defining structured templates |
| **Placeholder Validation** | `backend/src/rapid_reports_ai/template_manager.py` (L27-63, L65-150) | Extract & validate placeholders |
| **Prompt Construction** | `backend/src/rapid_reports_ai/template_manager.py` (L2123-2177) | Build structured filling prompt |
| **Post-Gen Detection** | `frontend/src/lib/utils/placeholderDetection.ts` | Detect unfilled placeholders in output |
| **Interactive Editing** | `frontend/src/routes/components/UnfilledItemHoverPopup.svelte` | Quick-fill UI for missed items |

---

## 2. Critical Issues & Recommendations

### 2.1 ❌ ISSUE: Blank Sections (Unaddressed Input Gaps)

**Problem**: Template may have sections with no corresponding input data (e.g., "PERFUSION ASSESSMENT" header in template but no perfusion findings dictated).

**Current Behavior** (from code analysis):
- ❓ **Unknown** - The prompt instructs AI to "fill in blanks" but doesn't explicitly handle missing data
- Line 2166 in template_manager.py: `"For XXX or XXXmm: Replace with actual measurements if provided; if not, use clinical estimate or remove."`
- This only covers measurements, **not entire sections**

**Expected AI Behavior** (from prompt):
```python
# backend/src/rapid_reports_ai/template_manager.py:2149-2177
"""
**Goal**: Complete the provided structured template by filling in blanks, 
replacing tilled variables (~VAR~), and making logical selections...
"""
```

The prompt **does not specify** what to do with sections that have:
- Headers present in template
- No corresponding findings in user input
- No placeholders (just static prose)

**Actual Risk**:
1. AI may **hallucinate** content to fill blank sections
2. AI may **leave sections verbatim** from template (showing normal findings when section wasn't assessed)
3. AI may **omit sections** inconsistently

#### Recommendations:

**Option A: Explicit Section Markers (Recommended)**
Add optional section markers to template syntax:

```
[Optional: Include only if perfusion imaging performed]
PERFUSION ASSESSMENT
First-pass perfusion demonstrates perfusion defect present/absent in the xxx territory.
```

This is **already partially implemented** (L944-989 in template_manager.py) but not clearly documented or enforced!

**Option B: Post-Generation Pattern Detection**
Extend `placeholderDetection.ts` to detect:
```typescript
// New detection pattern
export function detectUnaddressedSections(content: string, templateSections: string[]): UnaddressedSection[] {
    // Logic: Find template sections that appear verbatim (unchanged) in output
    // Flag for user review: "This section may not have been assessed"
}
```

**Option C: Pre-Fill Instruction Enhancement**
Update prompt (L2144-2177) to include:
```
**Handling Sections Without Input**:
- If a section has no corresponding findings in user input:
  1. If section has [Optional] marker → Omit entirely
  2. If section has placeholders (xxx, ~VAR~) → Leave placeholders visible
  3. If section is static prose with no placeholders → Keep verbatim (assume normal)
```

**✅ RECOMMENDED APPROACH**: **Combination of A + C**
1. Use `[Optional]` markers for truly optional sections (already in template generation L944-989)
2. Update prompt to explicitly handle missing input for non-optional sections
3. Post-generation detection for review (not auto-fill)

---

### 2.2 ⚠️ ISSUE: Overloaded Bracket Semantics `[]`

**Problem**: Brackets `[]` serve **three different purposes**, creating ambiguity:

| Context | Meaning | Example |
|---------|---------|---------|
| **Alternative Selection** | "Pick one option" | `[normal/dilated]` |
| **Conditional Inclusion** | "Include if true" | `[delete if normal]` |
| **Instructional Guidance** | "Formatting hint for AI" | `[keep titles!][dont make things bold]` |

**Current Detection Logic** (placeholderDetection.ts:188-200):
```typescript
// Detects ALL [text] patterns as "instructions"
const instructionRegex = /\[([^\]]+)\]/g;
while ((match = instructionRegex.exec(text)) !== null) {
    // Skips markdown links [text](url)
    if (!afterMatch.trim().startsWith('(')) {
        items.instructions.push({ ... });
    }
}
```

**Ambiguity Example**:
```
[normal/dilated]  → Is this an alternative or an instruction?
[keep titles!]    → Is this an instruction or a conditional?
```

**User's Question**: "Are [] for instructional guidance overcomplicating things?"

#### Analysis:

**Arguments FOR keeping `[]` for instructions:**
- ✅ Allows meta-guidance without polluting template prose
- ✅ Clear visual distinction from prose content
- ✅ Can be stripped in final output

**Arguments AGAINST:**
- ❌ Semantic overload (3 different meanings)
- ❌ Harder for AI to parse correctly
- ❌ User confusion: "When do I use [] vs just writing text?"

#### Recommendations:

**Option 1: Eliminate `[]` for Instructions (Simplify)**
- Use `//` for all instructional guidance (already used in "guided_prose" mode)
- Reserve `[]` ONLY for alternatives/conditionals
- Clearer separation: `//` = instructions, `[]` = dynamic content

**Before**:
```
[keep titles!][dont make things bold]

LEFT VENTRICLE
Normal/increased indexed LV end-diastolic volume...
```

**After**:
```
// Keep titles! Don't make things bold

LEFT VENTRICLE
Normal/increased indexed LV end-diastolic volume...
```

**Option 2: Different Symbol for Instructions (Preserve Distinction)**
- Use `{{instruction}}` for meta-guidance
- Keep `[]` for alternatives/conditionals
- More explicit but adds another symbol

**Option 3: Semantic Prefix (Hybrid)**
- `[INSTRUCTION: text]` → Meta-guidance
- `[option1/option2]` → Alternative selection
- `[if condition: text]` → Conditional inclusion

**✅ RECOMMENDED**: **Option 1** (Eliminate `[]` for instructions)
- Simplifies mental model: `[]` = always dynamic content
- Aligns with existing "guided_prose" pattern (`//` for guidance)
- Reduces ambiguity in detection logic

---

### 2.3 🔍 ISSUE: Variable Placeholder Necessity (~VAR~)

**User's Question**: "Do we even need ~VAR~? Won't AI detect and insert based on input?"

#### Analysis:

**Current ~VAR~ Usage**:
```
LVEF=~LV_EF~%
```
→ Creates explicit input field in UI (implied by L942 comment: "keep to 5-7 max to avoid cluttered input forms")

**If removed, would become**:
```
LVEF=xxx%
```
→ Generic measurement placeholder

**Tradeoffs**:

| Aspect | With ~VAR~ | Without ~VAR~ (just xxx) |
|--------|-----------|--------------------------|
| **Semantic Clarity** | ✅ Explicit: "This is LVEF" | ❌ Generic: "This is some %" |
| **UI Input Forms** | ✅ Can create labeled fields | ❌ All measurements generic |
| **AI Matching** | ✅ Easier: "Find LVEF in input" | ⚠️ Harder: "What measurement is this?" |
| **Template Simplicity** | ❌ More syntax to learn | ✅ Fewer symbols |
| **Context Sensitivity** | ❌ User must pre-define fields | ✅ AI infers from context |

**Real-World Example**:
```
User dictates: "LVEF 45%, RVEF 52%, indexed LVEDV 145 ml/m2"

Template WITH ~VAR~:
  "LVEF=~LV_EF~%, RVEF=~RV_EF~%, indexed LVEDV=xxx ml/m2"
  → AI matches: LV_EF=45, RV_EF=52, xxx=145 ✅ High confidence

Template WITHOUT ~VAR~:
  "LVEF=xxx%, RVEF=xxx%, indexed LVEDV=xxx ml/m2"
  → AI must infer: "First xxx near 'LVEF' = 45, second near 'RVEF' = 52, third = 145"
  → More error-prone with similar measurements ⚠️
```

#### Recommendations:

**Verdict: KEEP ~VAR~ but make it optional**

**Rationale**:
1. **High-stakes subspecialty reporting** (your use case) benefits from explicit matching
2. **Reduces hallucination risk** (AI knows exactly what to fill)
3. **Enables better UI** (can show labeled input fields: "LV_EF [____]%")
4. **Backwards compatible** (can fall back to `xxx` for generic measurements)

**Suggested Rule**:
- Use `~VAR~` for **critical, named measurements** (LVEF, tumor diameter, vessel stenosis %)
- Use `xxx` for **generic, contextual measurements** (chamber sizes, nodule sizes)
- Limit `~VAR~` to 5-7 per template (already your guideline)

**Example Template**:
```
LEFT VENTRICLE
End-diastolic volume is normal/increased (xxx ml/m2).
Systolic function is normal/reduced (LVEF=~LVEF~%).

RIGHT VENTRICLE
RV size is normal/dilated (xxx ml/m2).
Systolic function is normal/reduced (RVEF=~RVEF~%).
```

**Detection Enhancement**:
When AI encounters `~LVEF~`:
1. Search input for "LVEF" or "LV EF" or "ejection fraction"
2. Extract associated numeric value
3. If not found → **Leave placeholder visible** (don't hallucinate)

---

### 2.4 ⚡ ISSUE: Alternative Symbols (Normal/increased) vs [a/b]

**Current Inconsistency**:
- Template generation prompt uses: `Normal/increased` (no brackets)
- Placeholder detection looks for: `word1/word2` (no brackets)
- Template wizard example shows: `[normal/mild]` (WITH brackets)

**From Step4_FindingsSetup.svelte (L124-127)**:
```svelte
features: [
    '~VAR~ : Variables to fill (e.g. ~EF~)',
    'XXX : Measurement placeholders',
    '[a/b] : Select one option (e.g. [normal/mild])',  // ← BRACKETS
    '[text] : Conditional text (include if true)'
]
```

**From template_manager.py (L976, L980-981)**:
```python
# EXAMPLE STRUCTURE (note consistent lowercase):
LEFT VENTRICLE
Normal/increased indexed LV end-diastolic volume...  # ← NO BRACKETS
```

#### Recommendations:

**✅ STANDARDIZE: Use `option1/option2` (NO brackets) for alternatives**

**Rationale**:
1. Clearer visual distinction from conditionals
2. Simpler for AI to parse
3. Matches backend template generation
4. Aligns with medical convention (e.g., "present/absent" commonly written without brackets)

**Update Frontend Wizard** (Step4_FindingsSetup.svelte L126):
```svelte
'opt1/opt2 : Select one option (e.g. normal/mild)',  // Remove brackets
```

**Updated Symbol Legend**:
| Symbol | Purpose | Example | Post-Gen Detection |
|--------|---------|---------|-------------------|
| `xxx` | Measurement blank | `xxx mm` | Highlight if remains |
| `~VAR~` | Named variable | `~LVEF~%` | Highlight if remains |
| `opt1/opt2` | Alternative (AI picks one) | `normal/increased` | Highlight if remains |
| `//` | Instructional guidance | `// Assess wall motion` | Strip before output |

---

## 3. Symbol Choice Evaluation

### 3.1 Current Placeholder Symbols

| Symbol | Intuitive? | Medical Familiarity | Collision Risk | Recommendation |
|--------|-----------|--------------------|--------------|--------------  |
| `xxx` | ✅ Yes (universal blank) | ✅ High (used in clinical notes) | ⚠️ Low (but case-sensitive) | **KEEP** (use lowercase only) |
| `~VAR~` | ⚠️ Moderate (tech-familiar) | ❌ Low (not medical convention) | ✅ Very low | **KEEP** (good distinctiveness) |
| `[text]` | ❌ **Ambiguous** (3 meanings) | ⚠️ Moderate | ⚠️ Moderate (markdown, arrays) | **REFACTOR** (see 2.2) |
| `opt1/opt2` | ✅ Yes (clear choice) | ✅ High (medical notes) | ⚠️ Low (but unit collisions) | **KEEP** (with unit filtering) |

### 3.2 Alternative Symbol Schemes (If Redesigning)

**Scheme A: Minimal (Recommended)**
- `___` : Measurements (more visible than xxx)
- `${VAR}` : Variables (shell-like, familiar to tech users)
- `opt1/opt2` : Alternatives (no change)
- `//` : Instructions (no change)

**Scheme B: Explicit**
- `[M:xxx]` : Measurements
- `[V:VAR]` : Variables
- `[A:opt1/opt2]` : Alternatives
- `//` : Instructions

**Verdict**: **Keep current symbols** with refinements from Section 2.

---

## 4. Hardcoding vs. AI Flexibility

**User's Concern**: "Are we hardcoding too much? Should AI just figure it out from context?"

### 4.1 Hardcoding Benefits (Your Current Approach)

✅ **Pros**:
1. **Deterministic output** - Reduces hallucination in high-stakes reporting
2. **Structural fidelity** - Guarantees formatting compliance (crucial for subspecialty standards)
3. **Audit trail** - Clear mapping: placeholder → filled value
4. **User control** - Radiologist dictates structure, not AI

❌ **Cons**:
1. **Upfront effort** - Must create templates (but wizard mitigates)
2. **Rigidity** - Hard to adapt template mid-report
3. **Cognitive load** - Users must learn placeholder syntax

### 4.2 AI Flexibility Alternative

**Hypothetical "Smart Fill" Mode**:
```
Template: "The left ventricle is [assess size and function]."
Input: "LV dilated, EF 35%"
AI Output: "The left ventricle is dilated with reduced systolic function (LVEF 35%)."
```

✅ **Pros**: Natural, no syntax learning
❌ **Cons**: 
- Unpredictable phrasing ("dilated with reduced function" vs "shows dilatation and dysfunction")
- May omit measurements user expects
- Harder to validate programmatically

### 4.3 Recommendation: **Hybrid Approach** (Best of Both)

**Tier 1: Strict Placeholders** (current structured template mode)
- Use for: Subspecialty reports with regulatory requirements (cardiac MRI, oncology)
- Placeholders: `~VAR~`, `xxx`, `opt1/opt2`

**Tier 2: Guided Flexibility** (already exists as "guided_prose")
- Use for: General radiology (CT chest, abdomen)
- Guidance: `// Assess: [aspects]` + normal prose

**Tier 3: Full AI** (already exists as "normal_template")
- Use for: Rapid dictation, low-stakes reporting
- AI rewrites based on findings

**Let users choose based on use case** ← You already have this! Just need clearer documentation of when to use each.

---

## 5. Blank Section Handling: Detailed Implementation

### 5.1 Recommended Detection Pattern

**Add to placeholderDetection.ts**:
```typescript
export interface UnaddressedSection {
    sectionName: string;     // e.g., "PERFUSION ASSESSMENT"
    lineNumber: number;
    reason: 'no_input' | 'unchanged_from_template' | 'all_placeholders_unfilled';
    confidence: number;      // 0-1 score
}

export function detectUnaddressedSections(
    generatedContent: string,
    templateContent: string
): UnaddressedSection[] {
    // 1. Parse template into sections (by headers)
    const templateSections = parseTemplateSections(templateContent);
    const outputSections = parseTemplateSections(generatedContent);
    
    const unaddressed: UnaddressedSection[] = [];
    
    for (const templateSection of templateSections) {
        const outputSection = outputSections.find(s => s.name === templateSection.name);
        
        if (!outputSection) {
            // Section omitted entirely
            unaddressed.push({
                sectionName: templateSection.name,
                lineNumber: templateSection.lineNumber,
                reason: 'no_input',
                confidence: 1.0
            });
        } else {
            // Section present - check if content changed
            const similarity = calculateSimilarity(
                templateSection.content,
                outputSection.content
            );
            
            if (similarity > 0.95) {
                // Content nearly identical → likely unaddressed
                unaddressed.push({
                    sectionName: templateSection.name,
                    lineNumber: outputSection.lineNumber,
                    reason: 'unchanged_from_template',
                    confidence: similarity
                });
            }
            
            // Check if section has ALL placeholders unfilled
            const placeholders = detectUnfilledPlaceholders(outputSection.content);
            if (placeholders.total > 0 && 
                placeholders.total === countPlaceholdersInSection(templateSection.content)) {
                unaddressed.push({
                    sectionName: templateSection.name,
                    lineNumber: outputSection.lineNumber,
                    reason: 'all_placeholders_unfilled',
                    confidence: 0.9
                });
            }
        }
    }
    
    return unaddressed;
}
```

### 5.2 UI Indication

**In ReportResponseViewer component**:
```svelte
{#if unaddressedSections.length > 0}
    <div class="warning-banner">
        <span>⚠️ {unaddressedSections.length} section(s) may not have been assessed:</span>
        <ul>
            {#each unaddressedSections as section}
                <li>
                    <strong>{section.sectionName}</strong>
                    <button on:click={() => scrollToSection(section.lineNumber)}>
                        Review →
                    </button>
                </li>
            {/each}
        </ul>
    </div>
{/if}
```

### 5.3 Prompt Enhancement

**Update template_manager.py:2144-2177**:
```python
prompt = f"""
### FINDINGS SECTION - Structured Fill-In Mode

... [existing content] ...

**Handling Sections Without Corresponding Input**:
1. If section marked [Optional: ...] AND no input provided → OMIT entire section
2. If section has placeholders (xxx, ~VAR~) AND no input → LEAVE PLACEHOLDERS VISIBLE (do not hallucinate)
3. If section is static prose with NO placeholders AND no contradictory input → KEEP VERBATIM
4. NEVER fabricate measurements or findings not present in user input

**Example**:
Template section:
  PERFUSION ASSESSMENT
  First-pass perfusion shows defect present/absent in xxx territory.

User input: (no perfusion mentioned)

Correct output:
  PERFUSION ASSESSMENT
  First-pass perfusion shows defect present/absent in xxx territory.
  (Placeholders remain visible for user to fill or delete section)

WRONG output:
  PERFUSION ASSESSMENT
  First-pass perfusion shows defect absent.
  (AI fabricated "absent" - not stated in input!)
"""
```

---

## 6. Testing & Validation

### 6.1 Test Cases for Blank Sections

**Test 1: Optional Section with No Input**
```
Template:
  [Optional: Include only if stress performed]
  STRESS IMAGING
  Stress perfusion shows xxx.

Input: "LVEF 55%, no wall motion abnormalities"

Expected: Section omitted entirely
```

**Test 2: Required Section with No Input**
```
Template:
  LEFT VENTRICLE
  LVEDV=~LVEDV~ ml/m2, LVEF=~LVEF~%

Input: "RV normal"

Expected: Section present with placeholders visible
  LEFT VENTRICLE
  LVEDV=~LVEDV~ ml/m2, LVEF=~LVEF~%
```

**Test 3: Section with Partial Input**
```
Template:
  LEFT VENTRICLE
  LVEDV=~LVEDV~ ml/m2, LVEF=~LVEF~%

Input: "LVEF 40%"

Expected: 
  LEFT VENTRICLE
  LVEDV=~LVEDV~ ml/m2, LVEF=40%
```

### 6.2 Detection Test Cases

**Test 1: xxx Detection (Case Insensitive)**
```typescript
assert(detectUnfilledPlaceholders("Size xxx mm").measurements.length === 1);
assert(detectUnfilledPlaceholders("Size XXX mm").measurements.length === 1);
assert(detectUnfilledPlaceholders("Size Xxx mm").measurements.length === 1);
```

**Test 2: Unit vs. Alternative**
```typescript
// Should NOT detect as alternative (unit)
assert(detectUnfilledPlaceholders("110 ml/m2").alternatives.length === 0);

// Should detect as alternative
assert(detectUnfilledPlaceholders("normal/increased").alternatives.length === 1);
```

**Test 3: Bracket Context**
```typescript
// Should detect as instruction
assert(detectUnfilledPlaceholders("[keep titles]").instructions.length === 1);

// Should NOT detect as instruction (markdown link)
assert(detectUnfilledPlaceholders("[link](url)").instructions.length === 0);
```

---

## 7. Implementation Priority

### Phase 1: Critical (Immediate)
1. ✅ **Standardize alternative syntax** - Remove brackets from `[a/b]` examples (frontend wizard)
2. ✅ **Enhance blank section prompt** - Add explicit handling rules (template_manager.py:2144-2177)
3. ✅ **Simplify `[]` semantics** - Migrate instructions to `//` (template generation prompts)

### Phase 2: Important (Next Sprint)
4. 🔍 **Implement blank section detection** - Add `detectUnaddressedSections()` (placeholderDetection.ts)
5. 🎨 **UI for unaddressed sections** - Warning banner + review buttons
6. 📝 **Documentation update** - Clear guide on when to use each placeholder type

### Phase 3: Enhancement (Future)
7. 🧪 **Comprehensive test suite** - Cover all placeholder edge cases
8. 📊 **Analytics** - Track which placeholders are most often left unfilled
9. 🤖 **Smart suggestions** - "This section might benefit from ~VAR~ placeholders"

---

## 8. Final Recommendations Summary

### Symbol System (Refined)
✅ **KEEP**:
- `xxx` - Measurements (standardize lowercase)
- `~VAR~` - Named variables (5-7 max, for critical fields)
- `opt1/opt2` - Alternatives (no brackets)
- `//` - Instructional guidance

❌ **REMOVE**:
- `[]` for instructions (migrate to `//`)

⚠️ **CLARIFY**:
- `[Optional: condition]` - Explicit optional section marker (already in code but underutilized)

### Architecture Verdict
Your current architecture is **fundamentally sound** for subspecialty reporting:
- ✅ Explicit placeholders reduce hallucination risk
- ✅ Post-generation detection provides safety net
- ✅ Hybrid approach (4 template styles) gives flexibility

**Key Gap**: Blank section handling needs explicit rules + UI indication.

### Implementation Path
1. **Quick wins** (2-3 hours): Fix symbol inconsistencies, enhance prompt
2. **Medium effort** (1-2 days): Add blank section detection + UI
3. **Long-term** (ongoing): Build test suite, collect user feedback, iterate

---

## 9. Questions for You

1. **Blank sections**: Do you want AI to be **conservative** (leave placeholders) or **smart** (omit if confident)? I recommend conservative.

2. **`[]` migration**: Should we do a **hard break** (all existing templates need updating) or **gradual migration** (support both `[]` and `//` for 6 months)?

3. **Variable necessity**: Are there specific modalities where `~VAR~` is **critical** vs. where `xxx` suffices? (e.g., cardiac MRI needs `~LVEF~` but CT chest can use generic `xxx mm`?)

4. **Error tolerance**: For subspecialty reports, should **any unfilled placeholder** block signing/finalization? (Hard stop vs. warning?)

---

## Appendix: Code References

**Key Backend Files**:
- `template_manager.py:27-63` - Placeholder extraction
- `template_manager.py:65-150` - Template validation
- `template_manager.py:928-989` - Structured template generation prompt
- `template_manager.py:2123-2177` - Structured filling prompt construction

**Key Frontend Files**:
- `Step4_FindingsSetup.svelte:113-144` - Template style explanation
- `Step4_FindingsSetup.svelte:406-429` - Syntax highlighting
- `placeholderDetection.ts:122-205` - Detection logic
- `placeholderDetection.ts:239-357` - Highlighting logic

**Detection Patterns**:
```typescript
// measurements: /\bxxx\b/gi (case insensitive)
// variables: /~(\w+)~/g
// alternatives: /\b([\w]+\/[\w²³⁴\^]+\d*)\b/g (with unit filtering)
// instructions: /\[([^\]]+)\]/g (excludes markdown links)
```

