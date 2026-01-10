# RadFlow Documentation

## Table of Contents
1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Core Workflows](#core-workflows)
4. [Features](#features)
5. [API Reference](#api-reference)
6. [Technical Architecture](#technical-architecture)
7. [User Guide](#user-guide)

---

## Overview

RadFlow is an AI-powered radiology reporting platform designed to streamline the creation, management, and enhancement of medical reports. The platform combines flexible template systems, intelligent AI assistance, and comprehensive quality control features.

### Key Capabilities
- **Instant Report Generation**: Transform raw findings into structured NHS-standard reports
- **Custom Template System**: Four distinct template types for different workflows
- **Intelligent Enhancement**: Automatic finding extraction, clinical guidelines, and completeness analysis
- **Interval Comparison**: AI-powered comparison of current vs prior scans
- **Version Control**: Complete history tracking for reports and templates
- **Real-time Dictation**: Medical-grade voice transcription
- **Quality Control**: Automatic detection of missing information and unfilled placeholders

---

## Getting Started

### Prerequisites
- Python 3.11+ for backend
- Node.js 18+ for frontend
- PostgreSQL (production) or SQLite (development)
- Required API keys:
  - Anthropic (Claude)
  - Groq (Qwen/Llama models)
  - Deepgram (optional, for dictation)
  - SMTP credentials (optional, for email)

### Quick Setup

**1. Backend Setup**
```bash
cd backend
poetry install
cp .env.example .env  # Configure API keys and database
poetry run uvicorn rapid_reports_ai.main:app --reload --host 0.0.0.0 --port 8000
```

**2. Frontend Setup**
```bash
cd frontend
npm install  # or bun install
npm run dev
```

**3. Access**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## Core Workflows

### 1. User Authentication Flow

#### Registration
1. User visits `/register`
2. Provides email, password, full name, optional signature
3. System sends verification email
4. User clicks link to verify email
5. Account activated, can now log in

#### Login
1. User enters email/password at `/login`
2. System validates credentials
3. JWT token issued with 7-day expiry
4. User redirected to main application

#### Password Reset
1. User clicks "Forgot Password" at login
2. System sends magic link to email
3. User clicks link (valid for 1 hour)
4. Sets new password
5. Can log in immediately

### 2. Report Generation Workflows

#### A. Instant Report (Auto Report)
**Use Case**: Quick report from raw findings without pre-configured template

**Workflow**:
1. Navigate to "Auto Report" tab
2. Select use case: "Radiology Report"
3. Fill in variables:
   - **Clinical History**: Patient background, indication
   - **Scan Type**: Imaging modality and technical details
   - **Findings**: Raw observations (unstructured)
4. Optional: Use voice dictation for findings
5. Click "Generate Report"
6. AI structures findings into proper sections:
   - COMPARISON
   - LIMITATIONS
   - FINDINGS
   - IMPRESSION

**Behind the scenes**:
- Uses specialized prompts (zai-glm-4.6 model)
- Transforms unstructured input → structured report
- Applies NHS formatting standards
- Generates clinical summary

#### B. Templated Report
**Use Case**: Generate reports using pre-configured custom templates

**Workflow**:
1. Navigate to "Templated Report" tab
2. Select template from your library
3. System displays dynamic input fields based on template
4. Fill in variables (template-specific)
5. Optional: Use voice dictation
6. Click "Generate Report"
7. AI fills in template according to content style

**Template Types** (see Template Creation section for details):
- Normal Template: AI adapts template language to findings
- Guided Template: Normal + inline // comments for AI guidance
- Structured Fill-In: Strict placeholder system ({VAR}, xxx, [opt1/opt2])
- Systematic Checklist: Bullet list AI expands systematically

### 3. Template Creation & Management

#### Creating Templates: Two Methods

**Method A: Template Wizard** (Guided Step-by-Step)

**Step 1: Scan Information**
- Scan type (e.g., "CT Chest", "MRI Brain")
- Contrast: No contrast, With IV contrast, Other
- Contrast phases (if applicable)
- Protocol details

**Step 2: Choose Creation Method**
- **Wizard**: Build template step-by-step
- **From Reports**: Analyze existing reports to extract template

**Step 3: Section Builder** (Wizard path)
Configure report sections:
- **Comparison**: Include prior comparisons (with/without input field)
- **Technique**: Technical parameters
- **Limitations**: Scan limitations
- **Clinical History**: Include in output or just for AI context

Set section order by drag-and-drop

**Step 4: Findings Setup** (CRITICAL STEP)

**4a. Choose Content Style**:

1. **Normal Template** (📋)
   - Paste your normal report text as template
   - AI learns your language and adapts it
   - Best for: General reporting, maintaining institutional voice
   - Example: "The lungs are clear. The pleural spaces are clear."
   - When pathology present: AI adapts: "There is a 4cm mass in RUL..."

2. **Guided Template** (📝)
   - Normal template + embedded // comments
   - Comments guide AI understanding
   - Example:
     ```
     The lungs are well aerated.
     // Assess nodules, masses, consolidation
     The pleural spaces are clear.
     // Cover pneumothorax, effusions
     ```
   - AI uses comments to interpret what to assess

3. **Structured Fill-In** (📐)
   - Strict placeholder system
   - Template preserved EXACTLY
   - Syntax:
     - `{VAR}`: Named variables (e.g., `{LVEF}`)
     - `xxx`: Measurement placeholders
     - `[opt1/opt2]`: Alternatives (AI selects based on findings)
     - `// instruction`: AI guidance (stripped from output)
   - Example:
     ```
     // Keep headers uppercase
     LEFT VENTRICLE
     LVEF is [normal/reduced] at {LVEF}%.
     Volume is xxx ml/m².
     ```
   - Best for: Structured reports requiring exact formatting

4. **Systematic Checklist** (✓)
   - Simple bullet-point list
   - AI generates findings for each item
   - Example template:
     ```
     - Lungs (parenchyma, nodules)
     - Pleural spaces
     - Mediastinum
     - Heart
     ```
   - AI expands each systematically

**4b. Advanced Settings** (Writing Style Optimizations):

**Primary Choice**: Template Fidelity vs Custom Style
- **Follow Template Style**: AI matches template's voice and structure
- **Choose Writing Style**: Pick Concise or Prose

**Additional Controls**:
- **Format**: Prose paragraphs, bullets, or numbered lists
- **Finding Sequence**: 
  - Clinical Priority: Critical findings first
  - Template Order: Exact template structure
- **Clinical Preferences**:
  - Differential Diagnosis: none/if_needed/always
  - Recommendations: specialist referral, workup, follow-up
  - Subsection Headers: Add anatomical headers

**Step 5: Impression Setup**
- Display name (default: "IMPRESSION")
- Verbosity: Brief (diagnosis only) or Prose (diagnosis + details)
- Format: Prose, bullets, or numbered
- Differential approach: none/if_needed/always
- Recommendations to include

**Step 6: Review**
- Preview complete template configuration
- Test generation with sample data
- View rendered template syntax

**Step 7: Save**
- Template name and description
- Tags for organization
- Pin template for quick access
- Global custom instructions (applies to all sections)

**Method B: From Reports** (Extract from Existing Reports)

**Step 3: Report Input**
- Paste 2-5 example reports
- System analyzes patterns

**Step 4: Analysis**
- AI extracts common structure
- Identifies variables and patterns
- Suggests template configuration

Then continue to Steps 5-7 as above.

#### Template Management

**Actions**:
- **Edit**: Modify template configuration
- **Duplicate**: Create copy for variation
- **Pin/Unpin**: Quick access to favorites
- **Delete**: Remove template
- **Version History**: View/restore previous versions

**Organization**:
- **Tags**: Categorize templates (e.g., "CT", "MRI", "Urgent")
  - Rename tags globally
  - Delete tags (removes from all templates)
- **Search**: Filter by name or tags
- **Sort**: By name, last used, creation date

### 4. Report Enhancement Workflow

After generating any report, enhance it with intelligent analysis:

#### Step 1: Trigger Enhancement
Click "Enhance Report" button → Opens Enhancement Sidebar

#### Step 2: Automatic Processing

**Phase 1: Finding Extraction** (Qwen 3-32B)
- AI identifies 3-5 consolidated clinical findings
- Optimizes findings for guideline search
- Handles complex multi-finding consolidation

**Phase 2: Guideline Search** (Perplexity + Llama 3.3-70B)
- For each finding:
  - Generates 2-3 specialized search queries
  - Searches medical literature
  - Synthesizes evidence-based guidelines
- Results include:
  - Diagnostic overview
  - Classification systems (BI-RADS, Fleischner, Bosniak, LI-RADS, etc.)
  - Measurement protocols with normal ranges
  - Imaging characteristics
  - Differential diagnoses
  - Follow-up imaging recommendations
  - Medical literature references

**Phase 3: Completeness Analysis** (Async, GPT-OSS-120B)
- Runs in background
- Analyzes report thoroughness
- Identifies missing elements
- Suggests improvements
- Generates structured action items

#### Step 3: Review Enhancement Data

**Guidelines Tab**:
- Expandable cards for each finding
- Clinical context and evidence
- Quick reference during reporting

**Analysis Tab** (Currently hidden, redirects to Guidelines):
- Will show completeness analysis
- Action items for improvements

**Comparison Tab**: (See Interval Comparison section)

**Chat Tab**: Interactive AI assistance (see Chat Workflow)

### 5. Chat Enhancement Workflow

Conversational report improvement with surgical edits:

#### Step 1: Open Chat
Enhancement Sidebar → Chat tab

#### Step 2: Chat Interface
- **Input**: Free-text questions or requests
- **Context**: AI has full access to:
  - Current report content
  - Enhancement guidelines
  - Completeness analysis
  - Chat history

#### Step 3: Response Types

**A. Exploration** (Informational)
- User: "What are the implications of this finding?"
- AI: Provides clinical context, explains significance

**B. Edit Proposals** (Actionable)
- User: "The impression is too brief, expand it"
- AI: Proposes specific text changes
- Format: `<<<` old text `>>>` new text `<<<`
- User reviews and applies with one click

**C. Clarifications**
- User: "Should I add measurements?"
- AI: Recommends and explains

#### Step 4: Apply Edits
- Review proposed changes
- Click "Apply" on individual edits
- Changes integrated into report
- New version created automatically

#### Chat Features:
- **Context-Aware**: Understands full clinical picture
- **Surgical Edits**: Changes only what's requested
- **Undo/Redo**: Version control safety net
- **Chat History**: Full conversation preserved per report

### 6. Interval Comparison Workflow

AI-powered comparison of current report with prior scans:

#### Step 1: Access Comparison
Enhancement Sidebar → Comparison tab

#### Step 2: Add Prior Reports
- Click "Add Prior Report"
- Enter:
  - Prior report text
  - Study date (DD/MM/YYYY format)
  - Scan type
- Add multiple priors (compares against most recent)

#### Step 3: Run Analysis
Click "Analyse Interval Changes"

**AI Processing** (Two-Stage):

**Stage 1: Finding Classification**
For each finding in current report, determines:
- **NEW**: Only in current report
- **CHANGED**: Present in both, significantly different
  - Tracks measurements precisely
  - Calculates growth rates
  - Documents progression/regression
- **STABLE**: Present in both, no significant change
- **RESOLVED**: Was in prior, not in current

**Stage 2: Revised Report Generation**
- Integrates prior context
- Documents interval changes
- Includes dates and scan types
- Formats professionally

#### Step 4: Review Results

**Summary**: High-level assessment

**Clinical Analysis**:
- **Changed Findings**: Progression/regression with measurements
- **New Findings**: Recently identified abnormalities
- **Stable Findings**: Unchanged over time

**Report Modifications**:
- Shows what changed in revised report
- Explains reasoning for each modification

**Revised Report Preview**:
- Full new report with comparison context
- Can apply to replace current report

### 7. Quality Control: Unfilled Placeholder Detection

For structured templates, automatic detection of missing information:

#### Detection Triggers
- **On Report Generation**: Immediate scan
- **During Edit**: Real-time updates

#### Placeholder Types Detected

1. **Named Variables** (`{VAR}`)
   - Example: `{LVEF}`, `{PatientAge}`
   - Appears as purple highlight in report

2. **Measurement Placeholders** (`xxx`)
   - Example: "measures xxx cm"
   - Yellow highlight

3. **Alternatives** (`[opt1/opt2]`)
   - Not selected during generation
   - Orange highlight

4. **Blank Sections**
   - Empty section that should have content
   - Red highlight

#### User Actions

**Hover over Highlight**:
- Shows popup with:
  - Item type
  - Context
  - Fill options

**Fill Options**:
1. **Manual Entry**: Type/paste value
2. **AI Suggestion**: 
   - Click "Fill with AI"
   - AI analyzes context and proposes value
   - Review and accept/modify

**Bulk View**:
- Enhancement Sidebar → Shows all unfilled items
- Fill multiple at once
- Track completion status

### 8. Version Control

Both reports and templates maintain full version history:

#### Report Versions

**Automatic Version Creation**:
- Initial generation
- After chat edits
- After action application
- After comparison revision
- After manual updates

**Version Management**:
- View all versions with timestamps
- Compare any two versions (visual diff)
- Restore previous version
- Current version marked clearly

**Diff View**:
- Side-by-side comparison
- Additions highlighted green
- Deletions highlighted red
- Unchanged text in gray

#### Template Versions

**Automatic Saves**:
- On creation
- After each edit
- Before restoration

**Actions**:
- List all versions
- View version content
- Restore version (creates new version)
- Delete old versions (keeps current safe)

### 9. Settings & Configuration

#### User Settings (Settings Tab)

**Report Generation**:
- **Default Model**: Claude Sonnet 4 / Qwen 3 32B / Llama 3.3 70B
- **Auto-Save Reports**: Save generated reports automatically

**Signature**:
- Full name for report sign-off
- Optional professional details
- Applied to report footer

**API Keys** (User-Supplied):
- **Deepgram**: For personal dictation API quota
- Encrypted at rest
- Used instead of system key when present

**Account**:
- Email (read-only)
- Last login
- Registration date
- Logout option

#### System Configuration (.env)

Backend environment variables:
```env
# Required
ANTHROPIC_API_KEY=sk-...
GROQ_API_KEY=gsk_...

# Optional
DEEPGRAM_API_KEY=...  # System dictation fallback
DATABASE_URL=postgresql://...  # Defaults to SQLite
SECRET_KEY=...  # For JWT signing

# Email (optional)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=app_password
FRONTEND_URL=http://localhost:5173
```

### 10. Dictation Workflow

Real-time voice transcription using Deepgram Nova-3 Medical:

#### Setup
1. Ensure Deepgram API key configured (system or user)
2. Browser must support WebSocket

#### Usage

**Real-Time Dictation**:
1. Click microphone icon in text field
2. Grant browser microphone permission
3. Speak findings
4. Transcript appears in real-time
5. Click stop when done

**Pre-Recorded Audio**:
1. Upload audio file (MP3, WAV, etc.)
2. System transcribes and returns text
3. Insert into report field

**Features**:
- Medical vocabulary optimized
- Punctuation auto-inserted
- Real-time streaming
- Error handling and recovery

---

## Features

### Content Style Templates (In-Depth)

#### 1. Normal Template

**Concept**: Use any normal report as a template. AI learns your writing style and adapts it when pathology is present.

**When to Use**:
- General reporting
- Want to maintain consistent voice
- Template is descriptive prose

**How It Works**:
- You paste: "The lungs are clear. No pleural effusion. Mediastinum unremarkable."
- When pathology found, AI adapts:
  - "There is a 4cm spiculated mass in the right upper lobe."
  - "A moderate right pleural effusion is present."
  - "Enlarged mediastinal lymph nodes up to 2cm."
- AI preserves your:
  - Sentence structure
  - Medical terminology preference
  - Level of detail
  - Phrasing patterns

**Best Practices**:
- Use your actual normal reports
- Include full anatomical coverage
- Be consistent in terminology
- Natural, flowing prose works best

#### 2. Guided Template

**Concept**: Normal template + embedded // comments that guide AI understanding.

**When to Use**:
- Need AI to understand assessment context
- Complex findings requiring interpretation
- Want AI to make intelligent adaptations

**Comment Syntax**:
```
The lung parenchyma is normal.
// Assess for nodules, masses, consolidation, interstitial changes

The pleural spaces are clear.
// This section covers pneumothorax, effusions, pleural thickening
// Report presence, size, characteristics if abnormal
```

**How It Works**:
- Comments act as "colleague annotations"
- AI understands WHAT to look for
- AI knows HOW to report abnormalities
- Comments are stripped from final report

**Best Practices**:
- Use comments for complex assessments
- Explain clinical significance
- Guide reporting standards
- Clarify terminology preferences

#### 3. Structured Fill-In Template

**Concept**: Exact template preservation with smart placeholder filling.

**When to Use**:
- Need strict formatting
- Standardized reporting requirements
- Template is form-like
- High fidelity to exact structure required

**Placeholder System**:

**Named Variables** (`{VARNAME}`):
```
Left Ventricular Function:
LVEF is {LVEF}%.
Wall motion is {WallMotion}.
```
- User provides values
- AI inserts exactly as given
- Can be numbers, text, or clinical terms

**Measurement Placeholders** (`xxx`):
```
The mass measures xxx cm in maximum diameter.
Volume is xxx ml/m².
```
- AI extracts measurements from findings
- Inserts into exact position
- Maintains units and formatting

**Alternatives** (`[option1/option2/option3]`):
```
The ventricle is [normal/dilated/hypertrophied].
Systolic function is [preserved/mildly reduced/moderately reduced/severely reduced].
```
- AI selects appropriate option based on findings
- Can have 2+ options
- AI chooses most clinically accurate

**Instructions** (`// instruction`):
```
// Keep all section headers in UPPERCASE

LEFT VENTRICLE
// Report only if abnormality present
The LV shows {Abnormality}.

// Always report this section
RIGHT VENTRICLE  
The RV size is [normal/dilated].
```
- Provides AI guidance
- Stripped from output
- Controls generation behavior

**Example Template**:
```
// Use British English spelling throughout
// Keep headers uppercase

CARDIAC CHAMBERS

LEFT VENTRICLE
The left ventricle is [normal in size/dilated/hypertrophied].
LVEDD measures xxx mm (normal <56mm).
LVEF is {LVEF}%.
// Only include if wall motion abnormality present
[Wall motion: {WallMotionDescription}]

RIGHT VENTRICLE  
The right ventricle is [normal in size/dilated].
TAPSE measures xxx mm (normal >16mm).

LEFT ATRIUM
The left atrium is [normal in size/dilated].
LA volume is xxx ml/m² (normal <34ml/m²).

// Include only if present
[VALVULAR DISEASE:
{ValveDescription}]
```

**Best Practices**:
- Test placeholders thoroughly
- Use instructions for conditional logic
- Alternatives should be comprehensive
- Maintain consistent terminology

#### 4. Systematic Checklist

**Concept**: Simple bullet list that AI expands into complete findings.

**When to Use**:
- Want comprehensive coverage
- Ensure nothing missed
- Systematic organ-by-organ reporting

**Example Template**:
```
- Lungs (parenchyma, nodules, consolidation, interstitial changes)
- Pleural spaces (effusions, pneumothorax, thickening)
- Mediastinum (lymph nodes, vessels, airways, thymus)
- Heart and pericardium (size, effusion, calcifications)
- Chest wall and bones (soft tissue, ribs, vertebrae)
- Upper abdomen (liver, spleen, adrenals if visible)
```

**How It Works**:
- AI reads checklist items
- For each item, checks findings for relevant information
- Generates complete prose covering the structure
- Follows your writing style preferences

**Output Example**:
```
Lungs: There is a 4cm spiculated mass in the right upper lobe with surrounding ground glass opacity. No other nodules or consolidation. No interstitial abnormality.

Pleural spaces: A moderate right pleural effusion is present. No pneumothorax. No pleural thickening.

Mediastinum: Enlarged right paratracheal lymph nodes measure up to 2cm. The airways and major vessels are normal.

Heart and pericardium: The heart is normal in size. No pericardial effusion. No calcifications.

Chest wall and bones: The chest wall is unremarkable. No rib or vertebral lesions.

Upper abdomen: The visible upper abdomen is unremarkable.
```

**Best Practices**:
- Include parenthetical details for guidance
- Cover all relevant anatomy
- Be systematic (superior to inferior, etc.)
- Match your reporting order

### Writing Style Optimization (In-Depth)

#### Template Fidelity Toggle

**Concept**: Control whether AI matches your template's exact voice or uses a preset style.

**When ON (Follow Template Style)**:
- AI analyzes template's:
  - Sentence structure
  - Vocabulary choices
  - Level of detail
  - Phrasing patterns
- Generates new text matching that style
- Best for institutional consistency

**When OFF (Choose Writing Style)**:
- Override template style
- Select Concise or Prose preset
- Gives direct control over verbosity

**Use Cases**:
- **ON**: Multi-author templates, institutional style guides
- **OFF**: Personal templates, want consistent style across different templates

#### Writing Style: Concise vs Prose

**Concise** (⚡):
- Essentials only
- Brief, direct statements
- Consultant-to-consultant style
- Strips non-clinical words

Example:
```
Large filling defects right PA extending to segmental branches. 
Additional defect left lower lobe. 
RV dilated, RV/LV ratio 1.3. 
Mild IVC reflux. 
Small right effusion.
```

**Prose** (⚖️):
- Balanced detail
- Natural sentence flow
- Complete sentences
- Clinically relevant context

Example:
```
Large filling defects are present in the right main pulmonary artery, 
extending into segmental branches. An additional filling defect is 
identified in the left lower lobe. The right ventricle is moderately 
dilated with an RV/LV ratio of 1.3. Mild IVC reflux suggests right 
heart strain. A small right pleural effusion is present.
```

#### Format Options

**Prose Paragraphs**:
- Natural flowing text
- Most readable
- Standard for most reports

**Bullet Points**:
- Structured list format
- Clear separation of findings
- Good for complex cases

**Numbered Lists**:
- Sequential findings
- Priority ordering
- Useful for impression sections

#### Finding Sequence

**Clinical Priority**:
- Critical findings first
- Significant findings next
- Incidental findings last
- AI determines importance

**Template Order**:
- Follows exact template structure
- Anatomical order preserved
- Matches institutional standards

#### Clinical Preferences

**Differential Diagnosis**:
- **None**: Omit differentials
- **If Needed**: Include for uncertain cases
- **Always**: Every finding gets DDx

**Recommendations**:
- Specialist referral
- Further workup
- Imaging follow-up
- Clinical correlation

**Subsection Headers**:
- Anatomical headers (CHEST:, ABDOMEN:, PELVIS:)
- Organizes long reports
- Improves readability

### Enhancement Features (In-Depth)

#### Finding Extraction

**Algorithm**:
1. Parse report content
2. Identify clinically significant findings
3. Consolidate related findings
4. Optimize for guideline search
5. Return 3-5 key findings

**Intelligence**:
- Distinguishes pathology from normal structures
- Combines related findings (e.g., "mass + lymphadenopathy")
- Prioritizes clinical significance
- Medical terminology normalization

**Example**:
Input Report: "There is a 4cm spiculated mass in the RUL with surrounding ground glass. Enlarged right paratracheal nodes up to 2cm. Small right effusion."

Extracted Findings:
1. "Right upper lobe lung mass with ground glass component"
2. "Right paratracheal lymphadenopathy"
3. "Right pleural effusion"

#### Clinical Guidelines Synthesis

**Process**:
1. For each finding, generate 2-3 specialized queries
2. Search Perplexity medical index
3. Synthesize evidence from multiple sources
4. Structure into radiologist-focused format

**Output Structure**:

**Diagnostic Overview**:
- Clinical context
- Significance
- Common presentations

**Classification Systems**:
- BI-RADS (breast imaging)
- Fleischner (pulmonary nodules)
- Bosniak (renal cysts)
- LI-RADS (liver lesions)
- TNM staging
- etc.

**Measurement Protocols**:
- Parameter to measure
- Measurement technique
- Normal ranges
- Significance thresholds

**Imaging Characteristics**:
- Key features to identify
- Distinguishing characteristics
- Clinical significance

**Differential Diagnoses**:
- Alternative diagnoses
- Imaging features for each
- Supporting/excluding factors

**Follow-Up Imaging**:
- Indication for follow-up
- Recommended modality
- Timing
- Technical specifications

**Medical References**:
- Source articles
- Guidelines documents
- Links to literature

#### Completeness Analysis

**Analysis Areas**:
1. **Comparison Section**: Prior exam reference present?
2. **Clinical Indication**: Documented?
3. **Technical Quality**: Limitations noted?
4. **Anatomical Coverage**: All relevant structures?
5. **Measurements**: Quantitative where appropriate?
6. **Characterization**: Findings fully described?
7. **Clinical Correlation**: Recommendations provided?

**Output Format**:
- Summary assessment
- Checklist of items
- Specific suggestions
- Proposed improvements

**Action Items**:
Each suggestion includes:
- Title
- Details
- Specific text patch to add

Example:
```
Title: Add Prior Comparison
Details: No prior exam referenced. Including comparison helps track disease progression.
Patch: "Compared to CT chest dated 15/08/2024, the right lower lobe nodule has increased from 8mm to 11mm."
```

### Interval Comparison (In-Depth)

#### Two-Stage Processing

**Stage 1: Analysis & Classification**

**Finding Identification**:
- Extract findings from current report
- Match against prior report findings
- Classify each finding status

**Status Determination**:
- **NEW**: 
  - Only in current report
  - Document as new finding
- **CHANGED**: 
  - Present in both reports
  - Significant difference detected
  - Calculate precise change
  - Determine progression/regression
- **STABLE**: 
  - Present in both reports
  - No significant change
  - Document stability
- **RESOLVED**:
  - Was in prior, absent in current
  - Document resolution

**Measurement Tracking**:
- Extract measurements from both reports
- Calculate absolute change (mm, cm, etc.)
- Calculate percentage change
- Estimate growth rate
- Compare against normal growth patterns

**Multiple Priors**:
- If >1 prior provided:
  - Track trend across all studies
  - Calculate average growth rate
  - Identify acceleration/deceleration
  - Document dates for each measurement

**Stage 2: Revised Report Generation**

**Integration Strategy**:
- Identifies where to add comparison context
- Maintains report structure
- Inserts dates and scan types
- Preserves original formatting

**Output Sections**:

**Summary**:
High-level assessment of changes

**Key Changes**:
List of significant modifications with:
- Reason for change
- Original text (from current report)
- Revised text (with comparison)

**Revised Report**:
Complete new report incorporating:
- All interval changes
- Prior dates
- Prior scan types
- Progression/stability documentation

**Example**:

Original Current Report:
```
FINDINGS
There is an 11mm nodule in the left upper lobe.
```

After Comparison (vs 12/09/2024 CT):
```
FINDINGS
There is an 11mm nodule in the left upper lobe, increased from 8mm on 12/09/2024 
CT chest, representing interval growth over 4 months.
```

#### Clinical Intelligence

**Significance Assessment**:
- Growth >25% considered significant
- Size thresholds trigger follow-up recommendations
- Regression noted and explained
- New findings highlighted

**Follow-Up Recommendations**:
- Based on guideline context
- Incorporates growth rate
- Considers clinical context
- Suggests appropriate interval

### Quality Control (In-Depth)

#### Unfilled Placeholder Detection

**Detection Algorithm**:
1. Parse report content after generation
2. Identify placeholder patterns
3. Check if filled during generation
4. Flag unfilled items

**Placeholder Types**:

**1. Named Variables** (`{VarName}`):
```
Original Template: "LVEF is {LVEF}%."
Unfilled: "LVEF is {LVEF}%."  ← Still contains {LVEF}
Filled: "LVEF is 45%."  ← Variable replaced
```

**2. Measurement Placeholders** (`xxx`):
```
Original Template: "The lesion measures xxx cm."
Unfilled: "The lesion measures xxx cm."  ← xxx still present
Filled: "The lesion measures 3.2 cm."  ← xxx replaced with value
```

**3. Alternatives** (`[opt1/opt2]`):
```
Original Template: "The ventricle is [normal/dilated]."
Unfilled: "The ventricle is [normal/dilated]."  ← Brackets still present
Filled: "The ventricle is dilated."  ← Option selected, brackets removed
```

**4. Blank Sections**:
```
TECHNIQUE

[Empty - should have content]

FINDINGS
```

#### Visual Indicators

**Report Display**:
- Unfilled items highlighted
- Color coding by type:
  - Purple: Named variables
  - Yellow: Measurements
  - Orange: Alternatives
  - Red: Blank sections
- Hover for details
- Click to fill

**Sidebar View**:
- List all unfilled items
- Grouped by type
- Sorted by position in report
- Batch filling interface

#### Fill Options

**Manual Fill**:
1. Click/hover item
2. Input field appears
3. Enter value
4. Apply to report
5. Highlight removed

**AI-Assisted Fill**:
1. Click "Fill with AI"
2. AI analyzes:
   - Report context
   - Finding descriptions
   - Clinical information
3. AI proposes value
4. User reviews
5. Accept/modify/reject
6. Apply to report

**Example AI Fill**:
```
Template: "The mass measures xxx cm"
Findings: "4cm mass in right upper lobe"
AI Suggestion: "4" → "The mass measures 4 cm"
```

#### Validation

**Continuous Checking**:
- After initial generation
- After chat edits
- After manual edits
- After comparison revision

**Completeness Scoring**:
- Count total placeholders
- Count filled placeholders
- Calculate % complete
- Display prominently

**Report Sign-Off**:
- Warning if unfilled items exist
- Can still export/save
- User acknowledges gaps

### Version Control (In-Depth)

#### Report Versioning

**Version Creation Events**:
1. **Initial Generation**: v1.0
2. **Chat Edit Applied**: v1.1, v1.2, etc.
3. **Enhancement Actions**: v2.0
4. **Comparison Revision**: v3.0
5. **Manual Edit**: Version increment
6. **Version Restoration**: New current version

**Version Metadata**:
- Version number
- Creation timestamp
- Author (system/user)
- Change description
- Content snapshot

**Version Operations**:

**List Versions**:
- Chronological display
- Current version highlighted
- Creation dates
- Change descriptions

**View Version**:
- Full content display
- Markdown rendering
- Metadata sidebar

**Compare Versions**:
- Select two versions
- Side-by-side display
- Diff highlighting:
  - Green: Additions
  - Red: Deletions
  - Gray: Unchanged
- Line-by-line granularity

**Restore Version**:
- Select old version
- Confirm restoration
- Creates new version (doesn't delete history)
- New version marked "Restored from v1.2"

#### Template Versioning

**Same Mechanics as Reports**:
- Full version history
- Compare/restore functionality
- Metadata tracking

**Use Cases**:
- Test template changes
- Roll back errors
- Track template evolution
- Compare approaches

---

## API Reference

### Authentication Endpoints

#### POST /api/auth/register
Register new user account.

**Request Body**:
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "full_name": "Dr. Jane Smith",
  "signature": "Dr. Jane Smith, MD\nConsultant Radiologist" // optional
}
```

**Response**:
```json
{
  "message": "User registered successfully. Please check your email to verify your account.",
  "user_id": "uuid"
}
```

#### POST /api/auth/login
Authenticate user and receive JWT token.

**Request Body**:
```json
{
  "username": "user@example.com",  // OAuth2 format uses username
  "password": "SecurePass123!"
}
```

**Response**:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "full_name": "Dr. Jane Smith",
    "email_verified": true
  }
}
```

#### GET /api/auth/me
Get current authenticated user information.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "Dr. Jane Smith",
  "signature": "Dr. Jane Smith, MD\nConsultant Radiologist",
  "email_verified": true,
  "created_at": "2024-01-15T10:30:00Z",
  "last_login": "2024-01-20T14:22:00Z"
}
```

#### POST /api/auth/forgot-password
Request password reset email.

**Request Body**:
```json
{
  "email": "user@example.com"
}
```

**Response**:
```json
{
  "message": "If an account exists with that email, a password reset link has been sent."
}
```

#### POST /api/auth/reset-password
Reset password with token from email.

**Request Body**:
```json
{
  "token": "reset-token-from-email",
  "new_password": "NewSecurePass123!"
}
```

**Response**:
```json
{
  "message": "Password reset successfully. You can now log in."
}
```

#### POST /api/auth/verify-email
Verify email address with token from email.

**Request Body**:
```json
{
  "token": "verification-token-from-email"
}
```

**Response**:
```json
{
  "message": "Email verified successfully. You can now log in."
}
```

#### POST /api/auth/resend-verification
Resend verification email.

**Request Body**:
```json
{
  "email": "user@example.com"
}
```

**Response**:
```json
{
  "message": "Verification email sent."
}
```

### Report Generation Endpoints

#### GET /api/use-cases
List available report generation use cases.

**Query Parameters**:
- `model` (optional): Filter by compatible model

**Response**:
```json
{
  "use_cases": [
    {
      "name": "radiology_report",
      "display_name": "Radiology Report",
      "description": "Generate professional NHS radiology reports",
      "category": "reports",
      "variables": ["CLINICAL_HISTORY", "SCAN_TYPE", "FINDINGS"]
    }
  ]
}
```

#### GET /api/prompt-details/{use_case}
Get detailed information about a specific use case.

**Path Parameters**:
- `use_case`: Use case name (e.g., "radiology_report")

**Query Parameters**:
- `model`: Model to use (default: "default")

**Response**:
```json
{
  "name": "radiology_report",
  "display_name": "Radiology Report",
  "description": "Generate professional NHS radiology reports",
  "variables": [
    {
      "name": "CLINICAL_HISTORY",
      "label": "Clinical History",
      "description": "Patient background and indication for scan"
    },
    {
      "name": "SCAN_TYPE",
      "label": "Scan Type",
      "description": "Imaging modality and technical details"
    },
    {
      "name": "FINDINGS",
      "label": "Findings",
      "description": "Raw clinical observations"
    }
  ]
}
```

#### POST /api/chat
Generate report from use case.

**Request Body**:
```json
{
  "message": "Not used for auto reports",
  "use_case": "radiology_report",
  "model": "zai-glm-4.6",
  "variables": {
    "CLINICAL_HISTORY": "65-year-old with chronic cough",
    "SCAN_TYPE": "CT Chest with IV contrast",
    "FINDINGS": "4cm spiculated mass RUL, right paratracheal nodes 2cm"
  },
  "continue_conversation": false
}
```

**Response**:
```json
{
  "response": "COMPARISON\nNo prior imaging available for comparison.\n\n...",
  "description": "Right upper lobe lung mass with lymphadenopathy",
  "scan_type": "CT Chest with IV contrast",
  "model_used": "zai-glm-4.6"
}
```

### Template Endpoints

#### GET /api/templates
List user's templates.

**Headers**:
```
Authorization: Bearer <token>
```

**Query Parameters**:
- `skip`: Pagination offset (default: 0)
- `limit`: Results per page (default: 100)
- `tag`: Filter by tag (optional)
- `search`: Search in name (optional)

**Response**:
```json
{
  "templates": [
    {
      "id": "uuid",
      "name": "CT Chest Template",
      "description": "Standard chest CT reporting template",
      "scan_type": "CT Chest",
      "contrast": "with_contrast",
      "contrast_phases": ["arterial", "venous"],
      "tags": ["CT", "Chest", "Routine"],
      "is_pinned": true,
      "usage_count": 45,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-20T14:00:00Z"
    }
  ],
  "total": 15
}
```

#### GET /api/templates/{template_id}
Get specific template details.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "id": "uuid",
  "name": "CT Chest Template",
  "description": "Standard chest CT reporting template",
  "scan_type": "CT Chest",
  "contrast": "with_contrast",
  "template_config": {
    "sections": {...},
    "findings_config": {...},
    "impression_config": {...}
  },
  "tags": ["CT", "Chest"],
  "is_pinned": true,
  "usage_count": 45,
  "created_at": "2024-01-15T10:00:00Z"
}
```

#### POST /api/templates
Create new template.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "name": "CT Chest Template",
  "description": "Standard chest CT template",
  "scan_type": "CT Chest",
  "contrast": "with_contrast",
  "contrast_phases": ["arterial", "venous"],
  "protocol_details": "3mm slices, lung and mediastinal windows",
  "template_config": {
    "sections": {
      "comparison": {"included": true, "has_input_field": true},
      "technique": {"included": true, "has_input_field": false},
      "limitations": {"included": false},
      "clinical_history": {"include_in_output": false}
    },
    "section_order": ["comparison", "technique", "findings", "impression"],
    "findings_config": {
      "content_style": "normal_template",
      "template_content": "The lungs are clear...",
      "advanced": {
        "writing_style": "prose",
        "organization": "clinical_priority"
      }
    },
    "impression_config": {
      "display_name": "IMPRESSION",
      "advanced": {
        "verbosity_style": "prose",
        "format": "prose"
      }
    }
  },
  "tags": ["CT", "Chest", "Routine"],
  "is_pinned": false
}
```

**Response**:
```json
{
  "success": true,
  "template_id": "uuid",
  "message": "Template created successfully"
}
```

#### PUT /api/templates/{template_id}
Update existing template.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**: Same as POST /api/templates

**Response**:
```json
{
  "success": true,
  "message": "Template updated successfully"
}
```

#### DELETE /api/templates/{template_id}
Delete template.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "message": "Template deleted successfully"
}
```

#### POST /api/templates/{template_id}/generate
Generate report from template.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "variable_values": {
    "CLINICAL_HISTORY": "65-year-old with chronic cough",
    "FINDINGS": "4cm mass RUL",
    "COMPARISON": "No prior available"
  },
  "model": "claude-sonnet-4-20250514"
}
```

**Response**:
```json
{
  "response": "COMPARISON\nNo prior imaging...",
  "description": "CT Chest showing RUL mass",
  "scan_type": "CT Chest with IV contrast",
  "model_used": "claude-sonnet-4-20250514",
  "report_id": "uuid"
}
```

#### POST /api/templates/{template_id}/toggle-pin
Pin or unpin template for quick access.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "is_pinned": true,
  "message": "Template pinned successfully"
}
```

#### GET /api/templates/tags
Get all tags used across user's templates.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "tags": ["CT", "MRI", "Chest", "Abdomen", "Urgent", "Routine"]
}
```

#### POST /api/templates/tags/rename
Rename a tag across all templates.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "old_tag": "Urgent",
  "new_tag": "Priority"
}
```

**Response**:
```json
{
  "success": true,
  "templates_updated": 5,
  "message": "Tag renamed successfully"
}
```

#### POST /api/templates/tags/delete
Delete a tag from all templates.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "tag": "Urgent"
}
```

**Response**:
```json
{
  "success": true,
  "templates_updated": 5,
  "message": "Tag deleted successfully"
}
```

### Template Version Endpoints

#### GET /api/templates/{template_id}/versions
List all versions of a template.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "versions": [
    {
      "id": "version-uuid",
      "version_number": 3,
      "created_at": "2024-01-20T14:00:00Z",
      "is_current": true,
      "change_description": "Updated findings section"
    },
    {
      "id": "version-uuid-2",
      "version_number": 2,
      "created_at": "2024-01-18T10:00:00Z",
      "is_current": false,
      "change_description": "Added impression configuration"
    }
  ]
}
```

#### GET /api/templates/{template_id}/versions/{version_id}
Get specific version content.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "id": "version-uuid",
  "version_number": 2,
  "template_config": {...},
  "created_at": "2024-01-18T10:00:00Z",
  "is_current": false
}
```

#### POST /api/templates/{template_id}/versions/{version_id}/restore
Restore a previous version (creates new current version).

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "message": "Template version restored successfully"
}
```

#### DELETE /api/templates/{template_id}/versions/{version_id}
Delete a specific version (cannot delete current).

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "message": "Template version deleted successfully"
}
```

### Report Management Endpoints

#### GET /api/reports
List user's generated reports.

**Headers**:
```
Authorization: Bearer <token>
```

**Query Parameters**:
- `report_type`: Filter by "auto" or "templated" (optional)
- `skip`: Pagination offset (default: 0)
- `limit`: Results per page (default: 50)

**Response**:
```json
{
  "reports": [
    {
      "id": "uuid",
      "report_type": "templated",
      "report_content": "COMPARISON\nNo prior...",
      "description": "CT Chest showing RUL mass",
      "scan_type": "CT Chest with IV contrast",
      "model_used": "claude-sonnet-4-20250514",
      "template_id": "template-uuid",
      "template_name": "CT Chest Template",
      "created_at": "2024-01-20T14:30:00Z"
    }
  ],
  "total": 127
}
```

#### GET /api/reports/{report_id}
Get specific report details.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "id": "uuid",
  "report_type": "templated",
  "report_content": "COMPARISON\nNo prior...",
  "description": "CT Chest showing RUL mass",
  "scan_type": "CT Chest with IV contrast",
  "model_used": "claude-sonnet-4-20250514",
  "template_id": "template-uuid",
  "input_data": {
    "variables": {...},
    "model": "claude-sonnet-4-20250514"
  },
  "created_at": "2024-01-20T14:30:00Z"
}
```

#### DELETE /api/reports/{report_id}
Delete a report.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "message": "Report deleted successfully"
}
```

#### PUT /api/reports/{report_id}/update
Update report content (creates new version).

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "report_content": "Updated report text...",
  "description": "Updated description" // optional
}
```

**Response**:
```json
{
  "success": true,
  "message": "Report updated successfully",
  "version_id": "new-version-uuid"
}
```

### Report Enhancement Endpoints

#### POST /api/reports/{report_id}/enhance
Start enhancement process (finding extraction + guideline search).

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "force_refresh": false  // optional, default false
}
```

**Response**:
```json
{
  "success": true,
  "findings": [
    {
      "finding": "Right upper lobe lung mass with ground glass component",
      "supporting_context": "4cm spiculated mass..."
    }
  ],
  "guidelines": [
    {
      "finding": {...},
      "diagnostic_overview": "Lung masses with spiculation...",
      "classification_systems": [
        {
          "name": "Lung-RADS",
          "grade_or_category": "Category 4B",
          "criteria": "Solid nodule >15mm with spiculation"
        }
      ],
      "measurement_protocols": [...],
      "differential_diagnoses": [...],
      "follow_up_imaging": [...],
      "sources": [...]
    }
  ],
  "completeness_pending": true
}
```

#### GET /api/reports/{report_id}/completeness
Get completeness analysis status/result.

**Headers**:
```
Authorization: Bearer <token>
```

**Response (Pending)**:
```json
{
  "pending": true,
  "status": "running"
}
```

**Response (Complete)**:
```json
{
  "pending": false,
  "analysis": "The report is comprehensive but could benefit from...",
  "structured": {
    "summary": {
      "title": "Overall Assessment",
      "details": "Report covers all major findings..."
    },
    "questions": [
      {
        "id": "q1",
        "prompt": "Should prior imaging comparison be added?"
      }
    ],
    "suggested_actions": [
      {
        "id": "action1",
        "title": "Add Measurement",
        "details": "Include precise lesion measurement",
        "patch": "The lesion measures 4.2 cm in maximum diameter."
      }
    ]
  }
}
```

#### POST /api/reports/{report_id}/chat
Chat with AI about report for improvements.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "message": "Expand the impression to include differential diagnoses",
  "context_mode": "full"  // or "minimal"
}
```

**Response**:
```json
{
  "response": "I'll expand the impression...",
  "edit_proposals": [
    {
      "original": "Bilateral pulmonary emboli with right heart strain.",
      "revised": "Bilateral pulmonary emboli with right heart strain. Differential considerations include chronic thromboembolic disease, though the acute presentation and RV dilation suggest acute PE. Clinical correlation recommended."
    }
  ]
}
```

#### POST /api/reports/{report_id}/apply-actions
Apply enhancement suggestions to report.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "action_ids": ["action1", "action2"],
  "additional_context": "Focus on measurement precision" // optional
}
```

**Response**:
```json
{
  "success": true,
  "updated_content": "Updated report with actions applied...",
  "version_id": "new-version-uuid"
}
```

### Interval Comparison Endpoints

#### POST /api/reports/{report_id}/compare
Analyze interval changes vs prior reports.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "prior_reports": [
    {
      "text": "Prior report content...",
      "date": "15/08/2024",
      "scan_type": "CT Chest without contrast"
    }
  ]
}
```

**Response**:
```json
{
  "success": true,
  "comparison": {
    "summary": "Interval progression of right upper lobe mass...",
    "findings": [
      {
        "finding_name": "Right upper lobe nodule",
        "status": "changed",
        "current_measurement": {"value": "11", "unit": "mm"},
        "prior_measurement": {"value": "8", "unit": "mm"},
        "prior_date": "15/08/2024",
        "change_description": "Increased from 8mm to 11mm over 4 months",
        "clinical_significance": "Significant growth suggests..."
      }
    ],
    "key_changes": [
      {
        "reason": "Document interval growth",
        "original": "There is an 11mm nodule in the left upper lobe.",
        "revised": "There is an 11mm nodule in the left upper lobe, increased from 8mm on 15/08/2024 CT chest."
      }
    ],
    "revised_report": "Complete report with comparison context..."
  }
}
```

#### POST /api/reports/{report_id}/apply-comparison
Apply comparison revision to report.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "revised_report": "Report content from comparison analysis..."
}
```

**Response**:
```json
{
  "success": true,
  "message": "Comparison report applied successfully",
  "version_id": "new-version-uuid"
}
```

### Report Version Endpoints

#### GET /api/reports/{report_id}/versions
List all versions of a report.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "versions": [
    {
      "id": "version-uuid",
      "version_number": 3,
      "report_content": "Full report content...",
      "description": "CT Chest showing RUL mass",
      "created_at": "2024-01-20T15:00:00Z",
      "is_current": true,
      "change_type": "chat_edit"
    }
  ]
}
```

#### GET /api/reports/{report_id}/versions/{version_id}
Get specific version content.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "id": "version-uuid",
  "version_number": 2,
  "report_content": "Previous version content...",
  "created_at": "2024-01-20T14:45:00Z",
  "is_current": false
}
```

#### POST /api/reports/{report_id}/versions/{version_id}/restore
Restore a previous version.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "message": "Report version restored successfully",
  "new_version_id": "restored-version-uuid"
}
```

### Settings Endpoints

#### GET /api/settings
Get user settings.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "settings": {
    "default_model": "claude-sonnet-4-20250514",
    "auto_save": true
  },
  "signature": "Dr. Jane Smith, MD\nConsultant Radiologist",
  "encrypted_deepgram_key": "encrypted-key-data"  // if user has personal key
}
```

#### POST /api/settings
Update user settings.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "settings": {
    "default_model": "qwen/qwen3-32b",
    "auto_save": false
  },
  "signature": "Dr. Jane Smith, MD, FRCR\nConsultant Radiologist",
  "deepgram_key": "your-personal-deepgram-key"  // optional
}
```

**Response**:
```json
{
  "success": true,
  "message": "Settings updated successfully"
}
```

#### GET /api/settings/status
Get API key configuration status.

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "anthropic_configured": true,
  "groq_configured": true,
  "deepgram_configured": true,
  "has_at_least_one_model": true,
  "using_user_keys": {
    "deepgram": true  // user has personal Deepgram key
  }
}
```

### Dictation Endpoints

#### WebSocket /api/transcribe
Real-time audio transcription.

**Connection**:
```javascript
const ws = new WebSocket('ws://localhost:8000/api/transcribe?token=<jwt-token>');
```

**Message Format (Client → Server)**:
```json
{
  "type": "audio",
  "data": "<base64-encoded-audio>"
}
```

**Message Format (Server → Client)**:
```json
{
  "type": "transcript",
  "text": "Transcribed text...",
  "is_final": false
}
```

**Stop Signal**:
```json
{
  "type": "stop"
}
```

#### POST /api/transcribe/pre-recorded
Transcribe uploaded audio file.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

**Request**:
- Form field `audio`: Audio file (MP3, WAV, etc.)

**Response**:
```json
{
  "transcript": "Complete transcribed text from audio file..."
}
```

### Template Wizard Helper Endpoints

#### POST /api/templates/generate-findings-content
AI-generate findings template content.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "scan_type": "CT Chest",
  "content_style": "normal_template",
  "context": "Chest CT with contrast"
}
```

**Response**:
```json
{
  "content": "The lungs are clear bilaterally with no focal consolidation...",
  "model_used": "claude-sonnet-4-20250514"
}
```

#### POST /api/templates/suggest-instructions
Get AI suggestions for custom instructions.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "scan_type": "CT Chest",
  "template_content": "The lungs are clear..."
}
```

**Response**:
```json
{
  "suggestions": "Consider including:\n- Specific measurements for any nodules\n- Lymph node characterization..."
}
```

#### POST /api/templates/analyze-reports
Analyze existing reports to extract template patterns.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "reports": [
    "Report 1 full text...",
    "Report 2 full text..."
  ]
}
```

**Response**:
```json
{
  "success": true,
  "analysis": {
    "common_structure": "COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION",
    "common_phrases": [...],
    "suggested_template": "Generated template content...",
    "variables_detected": ["COMPARISON", "CLINICAL_HISTORY"]
  }
}
```

#### POST /api/templates/extract-placeholders
Extract variables from template content.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "template_content": "LVEF is {LVEF}%. Volume xxx ml/m²."
}
```

**Response**:
```json
{
  "variables": [
    {
      "name": "LVEF",
      "type": "variable",
      "position": 8
    }
  ],
  "measurements": [
    {
      "placeholder": "xxx",
      "context": "Volume xxx ml/m²",
      "position": 28
    }
  ],
  "alternatives": []
}
```

#### POST /api/templates/validate-template
Validate template syntax.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "template_content": "LVEF is {LVEF}%. Volume xxx ml/m².",
  "content_style": "structured_template"
}
```

**Response (Valid)**:
```json
{
  "valid": true,
  "message": "Template syntax is valid"
}
```

**Response (Invalid)**:
```json
{
  "valid": false,
  "errors": [
    {
      "type": "unmatched_bracket",
      "message": "Alternative bracket not closed",
      "position": 45
    }
  ]
}
```

#### POST /api/templates/suggest-placeholder-fill
Get AI suggestion for filling a placeholder.

**Headers**:
```
Authorization: Bearer <token>
```

**Request Body**:
```json
{
  "report_content": "Full report text...",
  "placeholder": "xxx",
  "context": "The lesion measures xxx cm",
  "findings": "4cm mass in right upper lobe"
}
```

**Response**:
```json
{
  "suggestion": "4",
  "confidence": "high",
  "reasoning": "Extracted from 'mass' measurement in findings"
}
```

---

## Technical Architecture

### Backend Stack

**Framework**: FastAPI
- Python 3.11+
- Async/await for concurrent operations
- Pydantic for data validation
- OpenAPI/Swagger docs auto-generated

**Database**: 
- PostgreSQL (production)
- SQLite (development)
- SQLAlchemy ORM
- Alembic migrations

**AI Integration**:
- **Anthropic Claude**: Primary report generation
- **Groq (Qwen/Llama)**: Enhancement tasks, fallbacks
- **Cerebras (GPT-OSS-120B)**: Completeness analysis, comparisons
- **Perplexity**: Guideline search
- **Deepgram**: Voice transcription

**Security**:
- JWT authentication (7-day expiry)
- Argon2 password hashing
- AES-256 encryption for API keys
- CORS middleware
- Email verification

**Caching**:
- In-memory caching for enhancement results
- Guideline caching (based on finding text hash)
- Async completeness analysis

**Email**:
- SMTP integration
- Magic links for:
  - Email verification
  - Password reset
- Configurable templates

### Frontend Stack

**Framework**: SvelteKit
- Server-side rendering (SSR)
- File-based routing
- Component-based architecture

**Styling**: TailwindCSS
- Utility-first CSS
- Custom gradients and animations
- Dark theme optimized
- Responsive design

**State Management**:
- Svelte stores
- Auth store (JWT token)
- Reports store (client-side caching)
- Templates store (client-side caching)
- Settings store

**Key Libraries**:
- `marked`: Markdown rendering
- `diff-match-patch`: Version diff display
- `@benedicte/html-diff`: HTML-aware diffs

**Build Tool**: Vite
- Fast HMR (Hot Module Replacement)
- Optimized production builds
- Code splitting

### Database Schema

**Users Table**:
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    password_hash VARCHAR NOT NULL,
    full_name VARCHAR NOT NULL,
    signature TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    email_verification_token VARCHAR,
    settings JSONB,
    encrypted_deepgram_key TEXT,
    created_at TIMESTAMP,
    last_login TIMESTAMP
);
```

**Templates Table**:
```sql
CREATE TABLE templates (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR NOT NULL,
    description TEXT,
    scan_type VARCHAR,
    contrast VARCHAR,
    contrast_phases JSONB,
    protocol_details TEXT,
    template_config JSONB NOT NULL,
    tags JSONB,
    is_pinned BOOLEAN DEFAULT FALSE,
    usage_count INTEGER DEFAULT 0,
    current_version_id UUID,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Template Versions Table**:
```sql
CREATE TABLE template_versions (
    id UUID PRIMARY KEY,
    template_id UUID REFERENCES templates(id),
    version_number INTEGER NOT NULL,
    template_config JSONB NOT NULL,
    created_at TIMESTAMP,
    change_description TEXT
);
```

**Reports Table**:
```sql
CREATE TABLE reports (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    report_type VARCHAR NOT NULL,  -- 'auto' or 'templated'
    report_content TEXT NOT NULL,
    description VARCHAR,
    scan_type VARCHAR,
    model_used VARCHAR,
    template_id UUID REFERENCES templates(id),
    input_data JSONB,
    current_version_id UUID,
    created_at TIMESTAMP
);
```

**Report Versions Table**:
```sql
CREATE TABLE report_versions (
    id UUID PRIMARY KEY,
    report_id UUID REFERENCES reports(id),
    version_number INTEGER NOT NULL,
    report_content TEXT NOT NULL,
    description VARCHAR,
    created_at TIMESTAMP,
    change_type VARCHAR  -- 'initial', 'chat_edit', 'enhancement', etc.
);
```

**Password Reset Tokens Table**:
```sql
CREATE TABLE password_reset_tokens (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    token VARCHAR UNIQUE NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP
);
```

### AI Model Configuration

**Model Selection Logic**:
1. Check user's default model setting
2. Fallback to system default if not set
3. Verify API key availability
4. Use fallback model if primary fails

**Model Purposes**:
- **Claude Sonnet 4**: Report generation (best quality)
- **Qwen 3-32B**: Finding extraction (fast, accurate)
- **Llama 3.3-70B**: Guideline synthesis (strong reasoning)
- **GPT-OSS-120B**: Completeness analysis (high reasoning)
- **zai-glm-4.6**: Specialized radiology reports

**Fallback Hierarchy**:
```
Primary Model
  ↓ (on failure)
Fallback Model
  ↓ (on failure)
Error returned to user
```

### Caching Strategy

**Enhancement Results**:
```python
ENHANCEMENT_RESULTS: Dict[str, Dict] = {
    "report-id": {
        "findings": [...],
        "guidelines": [...],
        "timestamp": 1234567890,
        "pending": False
    }
}
```

**Completeness Results**:
```python
COMPLETENESS_RESULTS: Dict[str, Dict] = {
    "report-id": {
        "analysis": "...",
        "structured": {...}
    }
}
```

**Guideline Cache** (File-based):
- Key: Hash of finding text + report content
- Value: Guideline synthesis result
- TTL: None (permanent cache)
- Location: `backend/.cache/`

### Security Implementation

**Password Hashing** (Argon2):
```python
from argon2 import PasswordHasher
ph = PasswordHasher()
hashed = ph.hash(password)
ph.verify(hashed, password)  # Raises exception if invalid
```

**JWT Tokens**:
```python
token_data = {
    "sub": user.email,
    "user_id": str(user.id),
    "exp": datetime.utcnow() + timedelta(days=7)
}
token = jwt.encode(token_data, SECRET_KEY, algorithm="HS256")
```

**API Key Encryption** (AES-256):
```python
from cryptography.fernet import Fernet
cipher = Fernet(encryption_key)
encrypted = cipher.encrypt(api_key.encode())
decrypted = cipher.decrypt(encrypted).decode()
```

### Deployment Architecture

**Production Setup**:
```
Frontend (Vercel)
    ↓ HTTPS
Backend API (Railway)
    ↓
PostgreSQL Database (Railway)
```

**Environment Variables**:
- Frontend: `PUBLIC_API_URL`
- Backend: Multiple (see [Settings & Configuration](#9-settings--configuration))

**CORS Configuration**:
```python
allow_origins = [
    "http://localhost:5173",  # Development
    "https://rad-flow.uk",  # Production frontend
    "https://api.rad-flow.uk"  # Production API
]
```

### Performance Optimizations

**Async Processing**:
- Completeness analysis runs in background
- Doesn't block report generation
- Polling for results

**Caching**:
- Enhancement results cached per report
- Guidelines cached by finding hash
- Client-side store caching

**Database Indexing**:
- User ID indexes on all tables
- Template/Report ID indexes
- Created_at indexes for sorting

**Pagination**:
- Templates: 100 per page
- Reports: 50 per page
- Version history: All returned (typically <20)

---

## User Guide

### Getting Started

#### 1. Create Account
1. Visit `/register`
2. Fill in:
   - Email address
   - Password (min 8 characters)
   - Full name
   - Signature (optional)
3. Click "Register"
4. Check email for verification link
5. Click link to verify account
6. Log in with credentials

#### 2. Configure Settings
1. Click "Settings" tab
2. Set preferences:
   - Default AI model
   - Auto-save toggle
   - Signature
3. (Optional) Add personal Deepgram API key for dictation
4. Click "Save"

#### 3. Generate Your First Report

**Quick Start (Auto Report)**:
1. Stay on "Auto Report" tab
2. Enter clinical information:
   - Clinical History: "65-year-old with chronic cough"
   - Scan Type: "CT Chest with IV contrast"
   - Findings: "4cm spiculated mass RUL, small left effusion"
3. Click "Generate Report"
4. Review generated report

**Structured Approach (Create Template First)**:
1. Go to "Templated Report" tab
2. Click "Create New Template"
3. Follow wizard steps (see Template Creation Workflow)
4. Save template
5. Select template from dropdown
6. Fill in variables
7. Generate report

### Best Practices

#### Template Design

**DO**:
- Use real normal reports as Normal Template base
- Test templates with various findings
- Organize with descriptive tags
- Pin frequently-used templates
- Use version control when making changes

**DON'T**:
- Mix multiple content styles in one template
- Over-complicate with too many variables
- Forget to test edge cases
- Delete templates without versioning backup

#### Report Generation

**DO**:
- Provide comprehensive clinical history
- Be specific with scan technical details
- Use dictation for efficiency
- Review AI output carefully
- Enhance reports for quality assurance

**DON'T**:
- Trust AI output blindly
- Skip clinical correlation
- Ignore unfilled placeholders
- Forget to save important reports

#### Enhancement Usage

**DO**:
- Run enhancement on complex cases
- Review guideline references
- Use chat for specific improvements
- Compare with priors when available
- Apply quality control checks

**DON'T**:
- Skip completeness analysis
- Ignore suggested actions
- Apply chat edits without review
- Forget to check version history

### Troubleshooting

#### Report Generation Issues

**Problem**: "No API key configured"
- **Solution**: Admin must set ANTHROPIC_API_KEY or GROQ_API_KEY in .env

**Problem**: "Failed to generate report"
- **Check**: API key valid and has credits
- **Check**: Model is online (Groq/Anthropic status)
- **Try**: Different model from dropdown
- **Try**: Simplify findings input

**Problem**: Template variables not filled
- **Check**: Variable names match exactly (case-sensitive)
- **Check**: Variables provided in input
- **Try**: Use placeholder detection to identify issues

#### Enhancement Issues

**Problem**: "Enhancement failed"
- **Check**: Report contains valid clinical content
- **Try**: Refresh enhancement
- **Check**: Groq API key configured

**Problem**: Guidelines not appearing
- **Check**: Findings extracted successfully
- **Check**: Perplexity search working
- **Wait**: Guidelines cache may be rebuilding

**Problem**: Completeness pending forever
- **Check**: Backend logs for errors
- **Check**: Anthropic API key configured
- **Try**: Refresh page

#### Template Issues

**Problem**: Template not generating expected output
- **Check**: Content style matches template design
- **Check**: Advanced settings appropriate
- **Try**: Test with different AI models
- **Review**: Template syntax for errors

**Problem**: Structured placeholders not filling
- **Check**: Placeholder syntax correct
- **Check**: Alternatives have valid options
- **Try**: Use validation endpoint to check syntax

#### Dictation Issues

**Problem**: Microphone not working
- **Check**: Browser permissions granted
- **Check**: Deepgram API key configured
- **Try**: Different browser
- **Try**: Pre-recorded audio instead

**Problem**: Poor transcription accuracy
- **Check**: Audio quality (clear, no background noise)
- **Check**: Using Deepgram Nova-3 Medical model
- **Try**: Speaking more clearly
- **Try**: Shorter phrases

### FAQ

**Q: Can I use RadFlow offline?**
A: No, requires internet for AI API calls and database access.

**Q: Is my data secure?**
A: Yes, passwords are hashed, API keys encrypted, all data in secure database.

**Q: Can I export reports?**
A: Yes, copy report text. Future: PDF/DOCX export planned.

**Q: How much does it cost?**
A: App is free (beta). User pays for own API keys if configured.

**Q: What models are supported?**
A: Claude Sonnet 4, Qwen 3-32B, Llama 3.3-70B, GPT-OSS-120B, zai-glm-4.6.

**Q: Can I collaborate with colleagues?**
A: Not yet. Template sharing planned for future.

**Q: How long are reports stored?**
A: Indefinitely unless user deletes them.

**Q: Can I restore deleted templates/reports?**
A: No, deletion is permanent. Use version control for safety.

**Q: What happens if AI generates incorrect information?**
A: User responsible for reviewing and correcting. AI is assistive, not diagnostic.

**Q: Can I customize the AI behavior?**
A: Yes, via template advanced settings and custom instructions.

**Q: What's the difference between content styles?**
A: See [Content Style Templates](#content-style-templates-in-depth) section.

**Q: How do version comparisons work?**
A: Visual diff shows additions (green), deletions (red), unchanged (gray).

**Q: Can I use my own AI models?**
A: Currently no, but can configure your own API keys.

**Q: What if enhancement is too slow?**
A: Completeness runs async in background. Guidelines are fast (<10s).

**Q: Can I batch process multiple reports?**
A: Not yet. Single report at a time currently.

**Q: How accurate is the interval comparison?**
A: Very accurate for measurements. Review AI interpretations carefully.

**Q: What medical specialties are supported?**
A: Optimized for radiology. Other specialties may work but untested.

**Q: Can I customize report sections?**
A: Yes, fully configurable in template wizard.

**Q: What's the template usage count for?**
A: Tracks how often template is used. Helps identify favorites.

**Q: Can I reorder templates?**
A: Sorted by name, last used, or date. Pin favorites to top.

**Q: What happens to unfilled placeholders?**
A: Highlighted in report. Can fill manually or with AI assistance.

**Q: Is there a mobile app?**
A: Not yet. Web interface works on mobile browsers.

**Q: Can I integrate with PACS/RIS?**
A: Not yet. Integration planned for future enterprise version.

**Q: What languages are supported?**
A: English only. British English by default.

**Q: Can I change report after it's generated?**
A: Yes, via chat edits, manual updates, or enhancement actions.

**Q: How many versions are kept?**
A: All versions kept indefinitely unless manually deleted.

**Q: Can I search my report history?**
A: Basic filtering by type. Full-text search planned.

---

## Glossary

**Auto Report**: Quick report generation without pre-configured template

**Completeness Analysis**: AI assessment of report thoroughness and missing elements

**Content Style**: How AI interprets template (Normal, Guided, Structured, Checklist)

**Enhancement**: Process of extracting findings and searching guidelines

**Finding**: Clinical observation or pathology identified in report

**Guideline**: Evidence-based medical information about a finding

**Interval Comparison**: AI-powered comparison of current vs prior scans

**Placeholder**: Template element to be filled during generation ({VAR}, xxx, [opt1/opt2])

**Templated Report**: Report generated using pre-configured custom template

**Template Fidelity**: AI matching template's writing style vs using preset style

**Use Case**: Pre-built report generation workflow (e.g., "Radiology Report")

**Version**: Snapshot of report/template at specific point in time

**Writing Style**: Verbosity level (Concise vs Prose)

---

## Support & Feedback

For issues, questions, or feature requests:
- Open GitHub issue
- Contact: [Add contact info]
- Documentation: This file

---

**Last Updated**: January 2026
**Version**: 1.0
