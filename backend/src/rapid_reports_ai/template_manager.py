"""Template Manager for Custom Templates
Handles custom template operations similar to PromptManager but for user-created templates
"""
import logging
import re
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TemplateManager:
    """Manages custom user-created templates"""
    
    def extract_variables(self, template: str) -> List[str]:
        """
        Extract variable names from a template string
        Looks for {{VARIABLE_NAME}} pattern
        
        Args:
            template: The template string
            
        Returns:
            List of variable names found in the template
        """
        # Find all {{VARIABLE_NAME}} patterns
        pattern = r'\{\{(\w+)\}\}'
        variables = re.findall(pattern, template)
        return list(set(variables))  # Remove duplicates
    
    def extract_structured_placeholders(self, template: str) -> Dict[str, List[str]]:
        """
        Extract placeholders from a structured template.
        
        Args:
            template: The structured template string
            
        Returns:
            Dict with keys:
            - 'variables': List of {VARIABLE} patterns
            - 'measurements': List of XXX placeholder locations (case insensitive)
            - 'alternatives': List of [option1/option2] patterns (with brackets)
            - 'instructions': List of // instruction lines
        """
        # Extract {VARIABLE} patterns (changed from ~VARIABLE~)
        variables = re.findall(r'\{(\w+)\}', template)
        
        # Count XXX measurement placeholders (case insensitive: xxx, XXX, Xxx, etc.)
        measurements = re.findall(r'\b[Xx]{3}\b', template, re.IGNORECASE)
        
        # Extract [option1/option2] alternatives (must have brackets, support spaces and hyphens)
        # Match anything inside brackets that contains a slash
        alternatives = re.findall(r'\[([^\]]+?/[^\]]+?)\]', template)
        
        # Extract // instruction lines (exclude //UNFILLED: markers)
        instructions = re.findall(r'^//\s*(?!UNFILLED:)(.+)$', template, re.MULTILINE)
        
        return {
            'variables': list(set(variables)),
            'measurements': measurements,  # Keep duplicates for count
            'alternatives': list(set(alternatives)),
            'instructions': instructions
        }
    
    def validate_structured_template(self, template: str) -> Dict[str, Any]:
        """
        Validate a structured template and return errors, warnings, and stats.
        
        Args:
            template: The structured template string
            
        Returns:
            Dict with keys:
            - 'valid': bool - True if no errors
            - 'errors': List of error dicts with 'type', 'message', 'line' (optional)
            - 'warnings': List of warning dicts with 'type', 'message'
            - 'stats': Dict with 'variables', 'measurements', 'conditionals', 'alternatives' counts
        """
        errors = []
        warnings = []
        lines = template.split('\n')
        
        # Extract stats using existing method
        placeholders = self.extract_structured_placeholders(template)
        stats = {
            'variables': len(placeholders['variables']),
            'measurements': len(placeholders['measurements']),
            'alternatives': len(placeholders['alternatives']),
            'instructions': len(placeholders['instructions'])
        }
        
        # Check for errors (breaks functionality)
        for i, line in enumerate(lines, 1):
            # Unbalanced brackets
            open_brackets = line.count('[')
            close_brackets = line.count(']')
            if open_brackets != close_brackets:
                errors.append({
                    'type': 'unbalanced_bracket',
                    'message': f'Unbalanced brackets at line {i}',
                    'line': i
                })
            
            # Unclosed variables (missing opening or closing brace)
            # Check for incomplete patterns that aren't part of valid {VAR} patterns
            if '{' in line or '}' in line:
                # Find all valid {VAR} patterns and their positions
                valid_patterns = []
                for match in re.finditer(r'\{(\w+)\}', line):
                    valid_patterns.append((match.start(), match.end()))
                
                # Find all potential incomplete patterns ({VAR or VAR})
                incomplete_matches = []
                # Pattern for {VAR (starts with { but doesn't have closing })
                for match in re.finditer(r'\{[^\s}]+(?!\})', line):
                    incomplete_matches.append((match.start(), match.end(), match.group()))
                # Pattern for VAR} (ends with } but doesn't have opening {)
                for match in re.finditer(r'(?<!\{)[^\s{}]+\}', line):
                    incomplete_matches.append((match.start(), match.end(), match.group()))
                
                # Filter out incomplete patterns that overlap with valid patterns
                actual_incomplete = []
                for inc_start, inc_end, inc_text in incomplete_matches:
                    overlaps = False
                    for val_start, val_end in valid_patterns:
                        # Check if incomplete pattern overlaps with any valid pattern
                        if not (inc_end <= val_start or inc_start >= val_end):
                            overlaps = True
                            break
                    if not overlaps:
                        actual_incomplete.append(inc_text)
                
                for var in actual_incomplete:
                    errors.append({
                        'type': 'unclosed_variable',
                        'message': f'Unclosed variable "{var}" at line {i}',
                        'line': i
                    })
            
            # Check for unbracketed alternatives (warn user to use brackets)
            # Look for word/word patterns that aren't units and aren't already in brackets
            unit_patterns = {'ml/m2', 'm/s', 'mmhg', 'cm2', 'mm2', 'cm3', 'ml/min', 'kg/m2', 'g/m2', 'l/min', 'bpm', 'beats/min', 'ml/m²', 'g/m²', 'l/min/m²'}
            
            # Find all [option1/option2] patterns (already bracketed alternatives)
            # Support spaces, hyphens, and any characters inside brackets
            bracketed_ranges = []  # Store (start, end) positions of bracketed alternatives
            for match in re.finditer(r'\[([^\]]+?/[^\]]+?)\]', line):
                # Store the character range of the entire bracket pattern including brackets
                bracketed_ranges.append((match.start(), match.end()))
            
            # Find all word/word patterns (including multi-option like word1/word2/word3)
            # Updated to support hyphens in words: [\w-]+ instead of \w+
            alternative_pattern = r'\b([\w-]+(?:/[\w-]+)+)\b'
            for match in re.finditer(alternative_pattern, line):
                alt_text = match.group(1)
                alt_start = match.start()
                alt_end = match.end()
                
                # Skip if it's a known unit
                if alt_text.lower() in unit_patterns:
                    continue
                
                # Skip if this alternative is inside any bracketed alternative range
                is_inside_brackets = False
                for br_start, br_end in bracketed_ranges:
                    # Check if the unbracketed alternative is inside the bracketed range
                    # (accounting for the brackets themselves)
                    if br_start < alt_start and alt_end < br_end:
                        is_inside_brackets = True
                        break
                
                if is_inside_brackets:
                    continue
                
                # Only warn if NOT already bracketed
                warnings.append({
                    'type': 'unbracketed_alternative',
                    'message': f'Alternative "{alt_text}" at line {i} should be wrapped in brackets: [{alt_text}]',
                    'line': i
                })
        
        # Check for double braces (malformed)
        if '{{' in template or '}}' in template:
            errors.append({
                'type': 'malformed_braces',
                'message': 'Found double braces ({{ or }}) - did you mean single brace ({VAR})?'
            })
        
        # Check for warnings (UX/quality concerns)
        if stats['variables'] > 10:
            warnings.append({
                'type': 'too_many_variables',
                'message': f'{stats["variables"]} variables detected - consider reducing to 5-7 for better UX',
                'count': stats['variables']
            })
        
        # Check for duplicate variable names (count occurrences in original template)
        all_variables = re.findall(r'\{(\w+)\}', template)
        variable_counts = {}
        for var in all_variables:
            variable_counts[var] = variable_counts.get(var, 0) + 1
        
        duplicates = [var for var, count in variable_counts.items() if count > 1]
        if duplicates:
            warnings.append({
                'type': 'duplicate_variables',
                'message': f'Duplicate variable names found: {", ".join(duplicates)}'
            })
        
        # Check if no placeholders detected (might not be a structured template)
        total_placeholders = stats['variables'] + stats['measurements'] + stats['alternatives']
        if total_placeholders == 0 and len(template.strip()) > 0:
            warnings.append({
                'type': 'no_placeholders',
                'message': 'No placeholders detected - this may not be a structured template'
            })
        
        result = {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'stats': stats,
            'placeholders': placeholders
        }
        return result
    
    # ========================================================================
    # Style Guidance and Normalization
    # ========================================================================
    
    def _normalize_advanced_config(self, advanced: dict, section_type: str = 'findings') -> dict:
        """
        Normalize advanced config by filling in defaults for missing fields.
        Ensures backward compatibility with templates created before new fields.
        
        Args:
            advanced: Current advanced config (may be incomplete)
            section_type: 'findings' or 'impression'
        
        Returns:
            Complete advanced config with defaults filled in
        """
        if section_type == 'findings':
            defaults = {
                'instructions': '',
                'writing_style': 'prose',  # concise or prose
                'follow_template_style': True,  # Only applies to normal_template and guided_template
                'format': 'prose',  # prose, bullets
                'use_subsection_headers': False,  # Standalone: can combine with any format
                'organization': 'template_order',  # clinical_priority, template_order
                'measurement_style': 'inline',
                'negative_findings_style': 'grouped',  # grouped, distributed, minimal, comprehensive
                'paragraph_grouping': 'by_finding',  # continuous, by_finding, by_region, by_subsection
                'descriptor_density': 'standard'
            }
        else:  # impression
            defaults = {
                'verbosity_style': 'prose',
                'format': 'prose',  # Frontend key; also canonical for impression_format
                'impression_format': 'prose',
                'differential_approach': 'if_needed',  # Frontend key
                'differential_style': 'if_needed',
                'comparison_terminology': 'measured',
                'measurement_inclusion': 'key_only',
                'incidental_handling': 'action_threshold',
                'recommendations': {
                    'specialist_referral': True,
                    'further_workup': True,
                    'imaging_followup': False,
                    'clinical_correlation': False
                },
                'instructions': ''
            }
        
        # Merge: existing values override defaults
        merged = {**defaults, **advanced}
        
        # BACKWARD COMPATIBILITY: Convert old fields to new structure
        if section_type == 'impression':
            # Normalize frontend keys to canonical keys for downstream consumers
            if 'format' in advanced and 'impression_format' not in advanced:
                merged['impression_format'] = advanced['format']
            if 'differential_approach' in advanced:
                diff_val = advanced['differential_approach']
                merged['differential_style'] = 'always_brief' if diff_val == 'always' else diff_val
            # Convert old verbosity (0-2) to new verbosity_style
            if 'verbosity_style' not in advanced and 'verbosity' in advanced:
                old_verbosity = advanced.get('verbosity', 0)
                if old_verbosity == 0:
                    merged['verbosity_style'] = 'brief'
                elif old_verbosity == 1:
                    merged['verbosity_style'] = 'prose'
                else:  # 2
                    merged['verbosity_style'] = 'prose'
        
        return merged
    
    # ========================================================================
    # Template Content Generation (AI-Powered)
    # ========================================================================
    
    async def generate_findings_content(
        self,
        scan_type: str,
        contrast: str,
        protocol_details: str,
        content_style: str,
        instructions: str = "",
        api_key: str = None
    ) -> str:
        """
        Generate FINDINGS template content via AI.
        Uses conditional prompt construction based on content_style for optimal results.
        
        Args:
            scan_type: Type of scan (e.g., "Chest CT")
            contrast: Contrast protocol
            protocol_details: Additional protocol details
            content_style: "normal_template", "guided_template", "checklist", "headers", or "structured_template"
            instructions: Optional custom instructions
            api_key: API key for LLM call
            
        Returns:
            Generated template content string
        """
        from pydantic import BaseModel
        from .enhancement_utils import (
            MODEL_CONFIG,
            _get_model_provider,
            _get_api_key_for_provider,
            _run_agent_with_model,
        )

        class TemplateContentOutput(BaseModel):
            content: str
        
        # Conditional system prompt based on style
        if content_style == "normal_template":
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template.

Generate a SUCCINCT normal findings template - gold standard concise normal statements.

CRITICAL - CONCISENESS RULES:
- Write brief, standard normal statements (e.g., "The lungs are clear with no focal consolidation, masses or nodules.")
- ONE sentence per major structure or anatomical group - combine related structures
- Avoid exhaustive lists of specific negatives - use broad statements
- NO excessive detail (e.g., "no endoluminal lesions or wall thickening" → just "patent")
- NO over-specification (e.g., list every vessel, every negative finding)
- Group structures logically: "The liver, spleen and pancreas are unremarkable"
- Target: 4-6 SHORT paragraphs for entire findings section, not 8-10 long ones

FORMAT RULES:
- Flowing prose paragraphs organized by anatomical region
- NO guidance comments, NO // lines, NO "Comment on..." text
- User will dictate ONLY abnormalities, and AI will replace relevant normal statements
- Use British English

EXAMPLES OF CONCISE VS VERBOSE:
❌ VERBOSE: "The trachea and main bronchi are patent with no endoluminal lesions or significant wall thickening. The carina is sharp and normally positioned."
✅ CONCISE: "The trachea and main bronchi are patent."

❌ VERBOSE: "The pleural spaces are clear with no pleural effusion, pneumothorax, or thickening. The pleural surfaces appear smooth with no pleural plaques or calcifications. The costophrenic angles are sharp with no blunting."
✅ CONCISE: "The pleural spaces are clear with no effusion or pneumothorax."

Do NOT include the "FINDINGS:" header - just the template content."""

        elif content_style == "guided_template":
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template.

Generate a template with normal findings as prose defining the REPORT STRUCTURE, enriched with // contextual annotations.

CONCEPTUAL APPROACH:
- The prose statements define the report's organizational flow and structure
- The // comments are like a senior colleague's annotations - providing contextual insights, principles, and assessment guidance
- // comments enrich understanding of what each section assesses and why

FORMAT RULES:
- Write normal finding prose statements that define the report structure
- Add // comment lines to provide contextual guidance and principle-based insights
- // comments can appear before, after, or inline with prose as needed
- Blank line between major anatomical regions
- Example:
  // Comment on study adequacy and technical factors first
  
  The trachea and main bronchi are patent and of normal calibre.
  // Assess: endoluminal lesions, extrinsic compression, abnormal tracheal configuration
  
  The mediastinum is of normal width and contour.
  // This section covers lymphadenopathy, masses, and vascular structures
- // lines are contextual enrichers for AI - they will NOT appear in final reports
- Use British English

Do NOT include the "FINDINGS:" header - just the template content."""

        elif content_style == "checklist":
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template.

Generate a systematic checklist as a bullet-point list of anatomical structures.

FORMAT RULES:
- Simple bullet list (e.g., "- Lungs (parenchyma, nodules, consolidation)")
- Brief parenthetical notes for key aspects to assess
- NO // comments, NO full paragraphs
- AI will generate complete findings covering each item systematically
- Use British English

Do NOT include the "FINDINGS:" header - just the template content."""

        elif content_style == "headers":
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template.

Generate section headers ONLY for anatomical regions.

FORMAT RULES:
- Clean section headers (e.g., "Lungs:")
- Two blank lines after each header for spacing
- NO content, NO guidance text, NO // comments
- AI will generate content under each header based on findings
- Use British English

Do NOT include the "FINDINGS:" header - just the template content."""

        elif content_style == "structured_template":
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template for structured fill-in reporting.

CORE PHILOSOPHY:
Generate templates that read like natural medical prose when filled, not robotic checklists. Balance systematic coverage with efficient, readable language.

═══════════════════════════════════════════════════════════════════

TEMPLATE ORGANIZATION:

1. SECTION HIERARCHY:
   
   Standard flow:
   - Study adequacy/quality statement (if relevant)
   - Primary anatomical/pathological sections
   - Clinical synthesis sections (for complex studies)
   - Ancillary/additional findings
   
   Example cardiac study:
   CONTRAST/ADEQUACY → VENTRICLES → VALVES → FUNCTION → PERFUSION → ADDITIONAL FINDINGS
   
   Example vascular study:
   ADEQUACY → ARTERIAL TREE (proximal→distal) → COLLATERALS → SEVERITY ASSESSMENT → SOFT TISSUES

2. BILATERAL/PAIRED STRUCTURES:
   
   INTEGRATE when structures typically assessed together:
   ✓ "Kidneys normal size bilaterally, no hydronephrosis"
   ✓ "Common iliac arteries: right xxx mm, left xxx mm"
   ✓ "Both ventricles normal size and function"
   
   SEPARATE when detailed independent assessment needed:
   ✓ LEFT VENTRICLE [detailed section]
   ✓ RIGHT VENTRICLE [detailed section]
   
   PRINCIPLE: Default to integration for efficiency. Separate only when each side needs extensive description.

3. SYNTHESIS SECTIONS (for complex multi-system studies):
   
   Include clinical interpretation sections beyond pure anatomy:
   
   Examples:
   - SEVERITY ASSESSMENT (vascular: pattern, runoff, functional impact)
   - FUNCTIONAL ASSESSMENT (cardiac: overall function, hemodynamic status)
   - PATTERN RECOGNITION (neuro: distribution, chronicity, differential clues)
   
   Format these as clinical synthesis, not anatomical inventory:
   ✓ "Disease pattern is [focal/diffuse/multilevel]"
   ✓ "Overall functional status is [preserved/reduced]"
   ✓ "Distribution suggests [vascular territory/pattern]"

═══════════════════════════════════════════════════════════════════

PROSE STYLE (CRITICAL - This determines readability):

1. NATURAL SENTENCE CONSTRUCTION:
   
   COMBINE related attributes in flowing sentences:
   
   ✓ GOOD: "Left ventricle size [normal/dilated] with end-diastolic volume xxx ml/m² and [preserved/reduced] systolic function (LVEF {LVEF}%)"
   
   ✗ BAD: "Left ventricle size is [normal/dilated]. End-diastolic volume is xxx ml/m². Systolic function is [preserved/reduced]. LVEF is {LVEF}%."
   
   ✓ GOOD: "Celiac trunk origin [normal/abnormal] from abdominal aorta with calibre xxx mm and [smooth/irregular] walls"
   
   ✗ BAD: "Origin is [normal/abnormal]. Calibre is xxx mm. Walls are [smooth/irregular]."

2. USE CONNECTORS FOR FLOW:
   
   Natural medical prose uses: "with", "and", "showing", commas
   
   ✓ "Mass measuring xxx mm with [irregular/smooth] margins and [homogeneous/heterogeneous] enhancement"
   ✓ "Kidney [normal/enlarged] in size, no hydronephrosis or masses"
   
   ✗ "Mass measures xxx mm. Margins are [irregular/smooth]. Enhancement is [homogeneous/heterogeneous]."

3. AVOID REPETITIVE "IS/ARE" STRUCTURE:
   
   ✗ "X is [finding]. Y is [finding]. Z is [finding]." ← Robotic checklist
   ✓ "X [finding] with Y [finding] and Z [finding]." ← Natural prose
   
   ✗ "Enhancement is [present/absent]. Size is xxx mm. Margins are [irregular/smooth]."
   ✓ "Enhancement [present/absent] with xxx mm [irregular/smooth] margins."

═══════════════════════════════════════════════════════════════════

MULTI-LEVEL ANATOMY - CRITICAL PATTERN (for spine, vascular, etc.):

When generating templates for anatomy assessed at multiple levels/locations:

AVOID: Binary "normal/abnormal" baselines that can be contradicted
AVOID: Global statements before level-specific findings

WRONG PATTERN (creates contradictions):
✗ "Facet joints appear [normal/abnormal] bilaterally..."
   Then user provides: "L5-S1 has hypertrophy"
   Result: "normal bilaterally... However, hypertrophy at L5-S1" ← CONTRADICTION

✗ "Central canal is [patent/stenotic] throughout"
   Then user provides: "stenosis at L4-L5"
   Result: Unclear if other levels normal or not assessed

CORRECT PATTERN (allows level-specific findings):

Option A - Presence-Based (Best for pathology):
✓ "[No/Present] [specific pathology] [if present: specify levels and severity]"

Example:
FACET JOINTS
[No/Present] facet joint hypertrophy [if present: specify levels]. [No/Present] facet arthropathy. [No/Present] facet joint effusion.

Option B - Level-by-Level (Best for systematic assessment):
✓ "At [level]: [finding]. At [level]: [finding]."

Example:
NEURAL FORAMINA
At L3-L4: right [patent/mild/moderate/severe stenosis], left [patent/mild/moderate/severe stenosis].
At L4-L5: right [patent/mild/moderate/severe stenosis], left [patent/mild/moderate/severe stenosis].
At L5-S1: right [patent/mild/moderate/severe stenosis], left [patent/mild/moderate/severe stenosis].

Option C - Conditional General Statement (For attributes that apply globally):
✓ "Disc heights [preserved/reduced] at all levels. [No/Mild/Moderate/Severe] disc desiccation."
   Then: "At L4-L5: [specific abnormality if present]."

Works because: "Heights preserved" doesn't contradict "herniation present" (different attributes)

WHEN TO USE EACH:

Use Option A (Presence-Based) when:
- Pathology can occur at any subset of levels
- Normal state is "absent"
- Examples: hypertrophy, effusion, fracture, mass

Use Option B (Level-by-Level) when:
- Need systematic documentation at each level
- Bilateral structures at each level
- Examples: foramina, facets at each disc level, vessel branches

Use Option C (Conditional General) when:
- Attribute applies globally (heights, signal, calibre)
- Then add specific pathology by level
- Examples: vertebral body heights, disc hydration

COMPLEX MULTI-FACTOR FINDINGS:

For findings with multiple contributing factors (e.g., stenosis from disc + facets + ligament):

✓ Integrate causes in description:
"At L5-S1: central canal stenosis (AP diameter xxx mm) due to disc protrusion, facet hypertrophy, and ligamentum flavum thickening."

✗ Don't scatter causes across sections:
DISC SECTION: "disc protrusion"
FACET SECTION: "facet hypertrophy"  
LIGAMENT SECTION: "ligamentum flavum thickening"
CANAL SECTION: "stenosis present" ← doesn't connect causes

Include // instruction:
// Describe stenosis with contributing factors: disc, facets, ligamentum flavum

═══════════════════════════════════════════════════════════════════

PLACEHOLDER TYPES (use EXACTLY as specified):

1. VARIABLES: {VAR_NAME}
   - For named measurements that need explicit matching
   - Example: "LVEF {LVEF}%" or "stenosis {SMA_STENOSIS}%"
   - Limit to 5-7 critical measurements only
   - Creates labeled input fields for user

2. MEASUREMENTS: xxx
   - Generic measurement blanks (always lowercase)
   - Example: "measuring xxx mm" or "calibre xxx mm"
   - Use when specific variable name not needed
   - Include units: "xxx mm" not just "xxx"

3. ALTERNATIVES: [option1/option2]
   
   CRITICAL RULES:
   • Brackets wrap ONLY the alternative words/phrases, NEVER entire sentences
   • Keep alternatives SIMPLE: single words or short phrases (2-3 words max per option)
   • Use SPARINGLY - only for 2-3 clear, mutually exclusive options
   • Each option must be grammatically compatible with surrounding sentence
   
   CORRECT EXAMPLES:
   ✓ "Size [normal/increased]" → integrates in sentence
   ✓ "Wall motion [normal/abnormal]" → simple binary
   ✓ "Enhancement [homogeneous/heterogeneous/none]" → clear mutually exclusive
   ✓ "[No/Mild/Moderate/Severe] stenosis" → works as sentence opener
   
   WRONG EXAMPLES (DO NOT DO):
   ✗ "[Size is normal/Size is increased]" → brackets wrap full phrases
   ✗ "[The lungs are clear/There is consolidation]" → different structures
   ✗ "Enhancement is [homogeneous with smooth margins/heterogeneous with irregular borders]" → options too complex
   ✗ "Effusion [present/absent/small/moderate/large]" → too many options, mixing binary with grades

4. CONDITIONAL INSTRUCTIONS: // instruction
   
   ACTIONABLE guidance for AI (stripped from output):
   
   Use SPARINGLY (2-4 per template) at key decision points:
   
   GOOD (actionable - tells AI what to do):
   ✓ // Describe only if abnormal
   ✓ // Only include if collaterals present  
   ✓ // Skip section if not assessed
   ✓ // Assess: vessel patency, stenosis, collateral formation
   
   BAD (just labels/comments - don't use):
   ✗ // Systematic assessment of structures
   ✗ // Cardiac function
   ✗ // This describes the kidneys
   
   WHEN TO USE:
   • Conditional sections (only fill if finding present)
   • Assessment reminders (key clinical features to check)
   • Handling instructions (skip if not evaluated)

═══════════════════════════════════════════════════════════════════

FORMATTING RULES:

- Section headers: UPPERCASE, no colons
- British English spelling: calibre, oedema, haemorrhage, tumour

═══════════════════════════════════════════════════════════════════

EXAMPLE TEMPLATES:

SIMPLE STUDY (minimal bilateral):

KIDNEYS
Kidneys [normal/abnormal] in size bilaterally [if abnormal: right xxx cm, left xxx cm]. [No/Present] hydronephrosis, calculi, or masses. Pelvicalyceal systems [normal/dilated].
// Describe only if abnormal

COMPLEX STUDY (detailed bilateral + synthesis):

ARTERIAL ASSESSMENT

ILIAC ARTERIES
Common iliac arteries: right xxx mm, left xxx mm. [No/Mild/Moderate/Severe] stenosis [if stenosis: right {CIA_R_STENOSIS}%, left {CIA_L_STENOSIS}%].
External iliac arteries [patent/occluded] bilaterally.
// Assess: patency, stenosis severity, calcification

FEMORAL ARTERIES
Superficial femoral arteries: right [patent/occluded segment xxx cm], left [patent/occluded segment xxx cm].
Profunda femoris arteries [patent/occluded] bilaterally.

SEVERITY ASSESSMENT
Disease pattern is [focal/diffuse/multilevel]. Runoff is [three-vessel/two-vessel/single-vessel/poor].
Most affected side is [right/left/bilateral symmetric].

═══════════════════════════════════════════════════════════════════

QUALITY CHECKLIST:

Before finalizing, verify:
□ Would this read naturally when filled? (Not checklist-style)
□ Are related attributes combined in flowing sentences?
□ Are bilateral structures integrated where appropriate?
□ Are synthesis sections included for complex studies?
□ Are alternatives simple and grammatically compatible?
□ Do // instructions provide actionable guidance?
□ Is systematic coverage complete?
□ Would a specialist find this useful for clinical decisions?

═══════════════════════════════════════════════════════════════════

ANTI-PATTERNS TO AVOID:

✗ Repetitive "X is [Y]. Z is [A]." structure throughout
✗ Separate sentences for each attribute of same structure
✗ Bilateral structures rigidly separated when integration makes sense
✗ Missing synthesis sections in complex multi-level studies
✗ Alternatives wrapping entire phrases or sentences
✗ Overuse of alternatives (use only when genuinely needed)
✗ Descriptive // comments instead of actionable instructions
✗ Template longer than typical filled report would be

═══════════════════════════════════════════════════════════════════

Now generate the structured fill-in template for the requested study. Focus on natural prose construction and efficient organization. Do NOT include the "FINDINGS:" header - just the template content.
"""
        
        else:
            # Fallback
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template. Use British English."""

        # Conditional user prompt based on style
        if content_style == "normal_template":
            user_prompt = f"""Create a SUCCINCT NORMAL TEMPLATE for the FINDINGS section.

Scan Type: {scan_type}
Contrast: {contrast}
Protocol: {protocol_details or "Standard protocol"}
Instructions: {instructions or "Standard systematic anatomical review"}

Write CONCISE, gold-standard normal findings. Brief statements covering all structures. The user will dictate only abnormalities later, and AI will replace the relevant normal statements.

CRITICAL REQUIREMENTS:
- Keep it SHORT - aim for 4-6 compact paragraphs total
- ONE sentence per major structure/region - combine related structures
- Broad normal statements, not exhaustive negative lists
- Group efficiently: "The liver, spleen and adrenals are unremarkable"

Example format (CONCISE):
The lungs are clear with no focal consolidation, masses or nodules. The pleural spaces are clear with no effusion or pneumothorax.

The mediastinum is unremarkable with no lymphadenopathy. The heart is normal in size with no pericardial effusion.

The visualised upper abdomen is unremarkable.

Generate the CONCISE normal template now. Remember: brevity is key - this is a template, not a comprehensive report."""

        elif content_style == "guided_template":
            user_prompt = f"""Create a GUIDED TEMPLATE for the FINDINGS section.

Scan Type: {scan_type}
Contrast: {contrast}
Protocol: {protocol_details or "Standard protocol"}
Instructions: {instructions or "Standard systematic anatomical review"}

Write template content describing normal findings, with // comment lines providing guidance on what to assess.

Format:
Template content describing normal findings.
// Assess: [comma-separated list of aspects to evaluate]

[blank line]

Next template content.
// Assess: [comma-separated list]

Example:
The trachea and main bronchi are patent and of normal calibre.
// Assess: endoluminal lesions, extrinsic compression, abnormal tracheal configuration

The lungs are well aerated.
// Assess: consolidation, ground glass opacities, nodules, masses (with size and location)

Generate the complete guided template now."""

        elif content_style == "checklist":
            user_prompt = f"""Create a CHECKLIST template for the FINDINGS section.

Scan Type: {scan_type}
Contrast: {contrast}
Protocol: {protocol_details or "Standard protocol"}
Instructions: {instructions or "Standard systematic anatomical review"}

Write a bullet-point checklist of anatomical structures to assess systematically.

Format:
- Structure name (key aspects, sub-structures)

Example:
- Lungs (parenchyma, nodules, consolidation, ground glass)
- Pleural spaces (effusions, pneumothorax, thickening)
- Mediastinum (lymph nodes with size, masses, vessels)
- Heart (size, chambers, pericardial effusion)

Generate the complete checklist now."""

        elif content_style == "headers":
            user_prompt = f"""Create a HEADERS-ONLY template for the FINDINGS section.

Scan Type: {scan_type}
Contrast: {contrast}
Protocol: {protocol_details or "Standard protocol"}
Instructions: {instructions or "Standard systematic anatomical review"}

Write section headers for anatomical regions. Headers only - no content, no guidance.

Format:
Header:

[two blank lines]

Next Header:

Example:
Lungs:


Pleural Spaces:


Mediastinum:


Heart:

Generate the complete headers template now."""

        elif content_style == "structured_template":
            user_prompt = f"""Create a STRUCTURED FILL-IN TEMPLATE for the FINDINGS section.

Scan Type: {scan_type}
Contrast: {contrast}
Protocol: {protocol_details or "Standard protocol"}
Instructions: {instructions or "Standard systematic anatomical review"}

CRITICAL PLACEHOLDER RULES:

1. {{VAR}} for named variables (5-7 max critical measurements only)

2. xxx for generic measurements (lowercase)

3. [option1/option2] for alternatives:
   - CRITICAL: Brackets wrap ONLY the alternative words/phrases, NEVER entire sentences
   - Keep alternatives SIMPLE: single words or short phrases (2-3 words max per option)
   - Use SPARINGLY - only when there are 2-3 clear, mutually exclusive options
   - Each option must work grammatically with the sentence
   - CORRECT: "Size is [normal/increased]" → "Size is normal" or "Size is increased"
   - WRONG: "[Size is normal/increased]" → brackets wrap full sentence
   - WRONG: "[No effusion/Effusion present]" → different structures, won't read well
   - WRONG: "Size is [normal/increased/decreased/enlarged]" → too many options

4. // for ACTIONABLE AI INSTRUCTIONS only (use sparingly, 2-4 max)

STRUCTURE GUIDANCE:
- Keep it SIMPLE and FLEXIBLE - just enough structure to guide the user
- Use clear section headers for major anatomical structures
- Pre-write complete prose with placeholders embedded naturally
- Don't over-complicate with excessive alternatives
- Focus on clarity and ease of use

Generate the template now. Remember: simplicity and clarity are key."""

        else:
            # Fallback
            user_prompt = f"""Create a FINDINGS section template for {scan_type} with {contrast} contrast."""

        # Get API key
        model_name = MODEL_CONFIG["TEMPLATE_FINDINGS_GENERATOR"]
        if not api_key:
            provider = _get_model_provider(model_name)
            api_key = _get_api_key_for_provider(provider)
        
        # Call LLM with higher temperature for variety
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=TemplateContentOutput,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={
                "temperature": 0.8,
                "top_p": 0.9,
                "max_completion_tokens": 4096
            }
        )
        
        return result.output.content
    
    async def suggest_instructions(
        self,
        section: str,
        scan_type: str,
        content_style: str = None,
        api_key: str = None
    ) -> List[str]:
        """
        AI-suggest instructions for FINDINGS or IMPRESSION sections.
        
        Args:
            section: "FINDINGS" or "IMPRESSION"
            scan_type: Type of scan
            content_style: Optional content style for FINDINGS
            api_key: API key for LLM call
            
        Returns:
            List of instruction suggestions
        """
        from pydantic import BaseModel
        from .enhancement_utils import (
            MODEL_CONFIG,
            _get_model_provider,
            _get_api_key_for_provider,
            _run_agent_with_model,
        )

        class InstructionsSuggestionsOutput(BaseModel):
            suggestions: List[str]
        
        system_prompt = """You are a senior consultant radiologist suggesting instructions for template sections.

Generate 3-5 concise instruction suggestions that guide AI report generation."""

        if section == "FINDINGS":
            user_prompt = f"""Suggest instructions for FINDINGS section template.

Scan Type: {scan_type}
Content Style: {content_style or "Not specified"}

Generate 3-5 instruction suggestions (one per line) that would help guide AI generation.
Examples:
- "Systematic anatomical review superior to inferior"
- "Always comment on lymph nodes"
- "Group related structures together"

Generate suggestions now."""
        else:  # IMPRESSION
            user_prompt = f"""Suggest instructions for IMPRESSION section template.

Scan Type: {scan_type}

Generate 3-5 instruction suggestions (one per line) for how the IMPRESSION should be generated.
Examples:
- "1-2 sentences. Direct statements."
- "Include differential if relevant"
- "Brief recommendations if non-obvious"

Generate suggestions now."""

        # Get API key  
        model_name = MODEL_CONFIG["TEMPLATE_INSTRUCTION_SUGGESTER"]
        if not api_key:
            provider = _get_model_provider(model_name)
            api_key = _get_api_key_for_provider(provider)
        
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=InstructionsSuggestionsOutput,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={
                "temperature": 0.7,
                "top_p": 0.9,
                "max_completion_tokens": 512
            }
        )
        
        return result.output.suggestions
    
    def _build_detailed_style_guidance(self, advanced: dict, section_type: str = 'findings', template_type: str = None) -> str:
        """
        Generate detailed, contextual writing style guidance from metadata.
        Provides concrete examples for each setting to ensure LLM compliance.
        
        Args:
            advanced: Advanced config dict with style preferences
            section_type: 'findings' or 'impression'
            template_type: 'normal_template', 'guided_template', or 'checklist' (optional)
        
        Returns:
            Formatted string with detailed style instructions
        """
        guidance_parts = []
        
        # Get template type from advanced dict if not passed explicitly
        if template_type is None:
            template_type = advanced.get('template_type', 'normal_template')
        
        # Check if template fidelity option is available (not for checklist)
        is_checklist = template_type == 'checklist'
        follow_template_style = False if is_checklist else advanced.get('follow_template_style', True)
        template_defines_style = False
        
        if not is_checklist:
            # Template fidelity option available for normal/guided templates
            if follow_template_style:
                # Template fidelity mode - principle-based, flexible guidance
                guidance_parts.append("""WRITING STYLE - TEMPLATE FIDELITY:

Emulate the template's linguistic character:
  - Observe the template's sentence structure patterns (complete vs. telegraphic vs. mixed)
  - Match its formality register (formal prose vs. concise clinical notes)
  - Mirror its use of medical terminology density and descriptor richness
  - Maintain similar rhythm and flow in phrasing

Your goal: Write in a voice that feels consistent with the template's established style

Refine for quality:
  - British English spelling and conventions
  - Medical terminology accuracy
  - Grammatical correctness and clarity
  - Measurement formatting consistency

Example: If template uses formal complete prose like "The liver demonstrates normal echotexture with no focal lesion", continue in that register throughout rather than shifting to telegraphic style.

Principle: Linguistic consistency with template, not rigid constraint. Adapt naturally while maintaining the established voice.""")
                
                # Skip the explicit style choice - template defines the style approach
                template_defines_style = True
        
        # Only proceed with style dict if template doesn't define style
        if not template_defines_style:
            # WRITING STYLE (merged verbosity + sentence structure for FINDINGS)
            writing_style = advanced.get('writing_style', 'prose')
            
            style_guidance = {
                'concise': """=== WRITING STYLE: CONCISE ===

COMMUNICATION GOAL:
Rapid consultant-to-consultant reporting. Maximum information density with zero ambiguity.

CORE PHILOSOPHY:
Adaptive telegraphic style - let complexity determine structure. Simple findings get pure telegraphic. Complex findings get minimal scaffolding for clarity.

KEY PRINCIPLES:

1. COMPLEXITY RULE:
   - Simple (1-2 attributes): No verbs. "Portal vein patent, normal calibre"
   - Grouped structures (compound subjects): Use linking verb. "Portal vein and superior mesenteric vein are patent with normal calibre"
   - Complex findings (3+ attributes): Add "shows". "Small bowel loops show wall thickening, reduced enhancement and pneumatosis"
   - Multiple normal attributes: Lead with "Normal". 
     ✓ "Normal small bowel wall thickness and enhancement"
     ✗ "Small bowel wall thickness and enhancement pattern normal"
     ✗ "Small bowel wall thickness normal, enhancement pattern normal"
     PATTERN: If describing normal attributes → "Normal [structure] [attribute 1] and [attribute 2]"

2. MINIMAL VERBS:
   - Default: "shows" (for complex findings with multiple attributes)
   - Exception: Linking verbs (are/is) allowed ONLY for grouped structures
     ✓ "Portal vein and superior mesenteric vein are patent" (compound subject)
     ✗ "Portal vein is patent" (single structure - omit verb)
   - Never: "demonstrates", "is present/noted/identified", "appears", "was/were"

3. MEASUREMENTS:
   - Parentheses for flow: (85% stenosis) not ", 85% stenosis,"
   - Direct: "4cm mass" not "mass measuring 4cm"
   - Remove: "approximately", "measuring"

4. STRUCTURE:
   - Keep essential connectors: "with", "at", "in", "from"
   - Remove: "There is", "evidence of", "the", "a", "an" (articles)
   - Commas separate attributes within same finding

5. NEGATIVES:
   - Single negative: "No free fluid"
   - Multiple negatives: Chain with commas: "No thrombosis, portal hypertension, or free fluid" (not "No thrombosis, no portal hypertension")
   - Never: "Absent [finding]" or "[finding] absent"

6. ANATOMICAL TERMS:
   - Spell out fully, no abbreviations
   - Minimal precision: "right upper lobe" not "lateral segment of right upper lobe"

DECISION TEST:
"Can a surgeon read this in 30 seconds under pressure without re-reading?"
If no → add minimal structure (usually "shows")

FORBIDDEN PHRASES:
"is/are present", "is identified", "demonstrates" (for simple findings), "approximately", "There is/are", "evidence of", "appears"

EXAMPLES:

Simple findings:
✓ "Portal vein patent, normal calibre"
✓ "Normal liver enhancement and attenuation, no focal lesions"
✗ "The portal vein is patent with normal calibre"
✗ "Liver enhancement normal, attenuation normal" (repetitive structure)

Grouped structures:
✓ "Portal vein and superior mesenteric vein are patent with normal calibre"
✗ "Portal vein, superior mesenteric vein patent, normal calibre" (too compressed when grouping)

Complex findings:
✓ "Superior mesenteric artery shows high-grade stenosis at origin (85% diameter reduction) with calcification"
✓ "Small bowel loops show wall thickening, reduced enhancement and mucosal irregularity"
✗ "The superior mesenteric artery demonstrates high-grade stenosis which is approximately 85%"

Negatives:
✓ "No thrombosis, portal hypertension, or free fluid"
✗ "No thrombosis, no portal hypertension, no free fluid" (repetitive)

CRITICAL: Apply this adaptive telegraphic style UNIFORMLY throughout the ENTIRE report - all findings, normal and abnormal.""",
                
                'prose': """=== WRITING STYLE: PROSE (Balanced NHS Prose) ===

COMMUNICATION GOAL:
Natural, readable medical prose. Professional register without unnecessary verbosity.

CORE PHILOSOPHY:
Balanced clarity - complete enough for comprehension, concise enough for efficiency. Natural consultant dictation rhythm.

KEY PRINCIPLES:

1. SENTENCE STRUCTURE:
   ✓ Default: Complete grammatical sentences with natural flow
   ✓ Vary opening patterns - avoid repetitive "The [structure] demonstrates/is/appears"
   ✓ Mix sentence lengths - combine short and medium sentences
   ✓ Acceptable: Efficient phrasing for simple findings when natural
   
   Example (good variation):
   "Severe coeliac axis compression by median arcuate ligament with post-stenotic dilatation. Collateral vessels from SMA to coeliac distribution via pancreaticoduodenal arcade. Common hepatic and splenic arteries normal distal to compression."
   
   Avoid (repetitive structure):
   "The coeliac axis demonstrates compression. The collateral vessels are seen. The common hepatic artery demonstrates normal calibre."

2. VERB CHOICES:
   ✓ Prefer: "shows" (clear and direct)
   ✓ Acceptable: "demonstrates" (use occasionally, not repetitively)
   ✓ Acceptable: Passive when natural ("is present", "are patent")
   ✗ Never: Padding verbs: "is noted", "are seen", "is identified", "is observed"
   ✗ Avoid: "There is/are..." sentence openings

3. ARTICLES:
   ✓ Use when introducing findings or for clarity: "The transition point shows mass"
   ✓ Omit when context clear: "Small pleural effusion", "Liver normal size"
   ✗ Don't start every sentence with "The [structure]"

4. MINIMIZE PASSIVE PADDING:
   ✓ "Post-stenotic dilatation present" or "Post-stenotic dilatation of coeliac trunk"
   ✗ "Post-stenotic dilatation is noted"
   ✓ "No free fluid"
   ✗ "No evidence of free fluid is identified"

5. REMOVE VERBOSE PHRASES:
   ✓ "no" or "without"
   ✗ "with no evidence of", "without evidence of"
   ✓ "normal calibre"
   ✗ "demonstrates normal calibre"

6. NEGATIVE FINDINGS:
   ✓ Consolidated: "No free fluid, pneumoperitoneum, or abscess"
   ✓ Simple: "No free fluid"
   ✗ Verbose: "No evidence of free fluid is identified"

EXAMPLES:

Abnormal findings:
✓ "Right upper lobe mass measuring 4 cm with spiculated margins and central cavitation. Enlarged right hilar lymph nodes (short axis 2 cm). Small right pleural effusion."

✗ "There is a 4 cm mass in the right upper lobe which demonstrates spiculated margins and central cavitation. Enlarged right hilar lymph nodes are seen measuring 2 cm in short axis. A small right pleural effusion is noted."

✓ "Small bowel obstruction at mid ileum with dilated proximal loops (up to 4 cm). Transition point shows intraluminal soft tissue mass. No free fluid or pneumoperitoneum."

✗ "There is evidence of small bowel obstruction at the level of the mid ileum with dilated proximal small bowel loops measuring up to 4 cm. The transition point demonstrates an intraluminal soft tissue mass. No evidence of free fluid or pneumoperitoneum is identified."

Normal findings:
✓ "Liver normal size with homogeneous enhancement, no focal lesions. Portal vein patent."

✗ "The liver is of normal size and demonstrates homogeneous enhancement with no focal lesions identified. The portal vein is patent."

FORBIDDEN PATTERNS:
- Repetitive "The [structure] demonstrates/is/appears..." (vary your openings!)
- "is noted", "are seen", "is identified", "is observed" (padding verbs that add nothing)
- "There is/are..." sentence openings
- "with no evidence of" → use "no" or "without"

CRITICAL: Apply this balanced prose style UNIFORMLY throughout the ENTIRE report - all findings, normal and abnormal. Aim for natural consultant dictation, not template reading."""
            }
            guidance_parts.append(style_guidance.get(writing_style, style_guidance['prose']))
        
        # MEASUREMENT STYLE
        measurement_style = advanced.get('measurement_style', 'inline')
        if measurement_style == 'inline':
            guidance_parts.append("MEASUREMENTS - INLINE INTEGRATION:\n  - Integrate measurements directly into descriptors\n  - Example: 'A 4cm spiculated mass...'\n  - NOT: 'A spiculated mass is present, measuring 4cm'")
        else:
            guidance_parts.append("MEASUREMENTS - SEPARATE CLAUSES:\n  - Report findings first, measurements after\n  - Example: 'A spiculated mass is present, measuring 4cm in maximum diameter'\n  - NOT: 'A 4cm spiculated mass...'")
        
        # ORGANIZATION (how findings are sequenced)
        organization = advanced.get('organization', 'clinical_priority')
        
        # Consolidation: 'problem_oriented' is now merged into 'clinical_priority'
        if organization == 'problem_oriented':
            organization = 'clinical_priority'
            
        org_guidance = {
            'clinical_priority': """ORGANIZATION - CLINICAL PRIORITY:
  KEY PRINCIPLE: Template structure is your organizational framework. Clinical priority elevates significant findings to lead position.
  
  SEQUENCE: 
    1. HEADLINE: Lead with acute/significant abnormalities if present
    2. IMMEDIATE CONTEXT: Complete the regional picture for that finding (related structures, complications)
    3. RETURN TO TEMPLATE: Resume template's structural flow for remaining findings
    4. SKIP DUPLICATES: When returning to template, skip any structures already addressed in steps 1-2
    5. Within each template section, prioritize: abnormal → pertinent negative → incidental normal
  
  EXAMPLE FLOW:
    • PE in right PA [HEADLINE] 
    • RV dilation with IVC reflux [IMMEDIATE CONTEXT]
    • [RETURN TO TEMPLATE - skip PA/heart sections already done]
    • Wedge consolidation in RLL [next template section: parenchyma]
    • Small pleural effusion [next template section: pleural space]
    • Remainder as per template structure
  
  CRITICAL: Each finding mentioned ONCE only. Template is your roadmap - clinical priority determines what to emphasize first.
  
  IMPORTANT DISTINCTION: This controls ORGANIZATION/STRUCTURE only (what order to report findings). Your LANGUAGE STYLE (how to phrase findings) is controlled by the Writing Style setting above - apply that style uniformly throughout the entire report, regardless of organizational sequence.
""",
            
            'template_order': """ORGANIZATION - TEMPLATE ORDER:
  KEY PRINCIPLE: Strictly follow template's defined anatomical sequence
  SEQUENCE: Exact order specified in template (may be custom, not standard anatomical)
  EXAMPLE: If template specifies "Pelvis → Abdomen → Chest", report in that exact order regardless of clinical significance
  
  NOTE: This controls STRUCTURE/SEQUENCE only. Language style is controlled by Writing Style setting - apply uniformly throughout.
"""
        }
        guidance_parts.append(org_guidance.get(organization, org_guidance['clinical_priority']))
        
        # NEGATIVE FINDINGS HANDLING
        if follow_template_style:
            guidance_parts.append("""NEGATIVE FINDINGS - PRESERVE TEMPLATE LANGUAGE:
  Keep all normal statements exactly as authored in the template.
  Do not consolidate, rephrase, or group structures differently
  from how they appear in the template body.
  Enumerate structures explicitly as the template does — do not
  collapse named structures into grouped summaries for brevity.""")
        else:
            negative_style = advanced.get('negative_findings_style', 'grouped')
            negative_guidance = {
                'minimal': """NEGATIVE FINDINGS - PERTINENT ONLY:
  STRUCTURE: Include ONLY negatives relevant to the abnormality and clinical context
  PRINCIPLE: Adapt negative findings to what's clinically significant given the positive findings
  SEQUENCE: Report negatives that help answer the clinical question or are relevant to staging/assessment
  
  EXAMPLES:
    - For lung mass: "No mediastinal lymphadenopathy. No pleural effusion."
    - For liver lesion: "No biliary dilatation. No ascites."
    - Omit routine normals (e.g., "liver normal") if not relevant to clinical question
  
  KEY PRINCIPLE: Clinical relevance determines inclusion, not completeness""",
                'grouped': """NEGATIVE FINDINGS - GROUPED:
  STRUCTURE: Combine related normal structures efficiently in single statements
  PRINCIPLE: Efficient consolidation of normals without excessive verbosity
  SEQUENCE: Group anatomically related structures together
  
  EXAMPLES:
    - "The liver, spleen and pancreas are unremarkable."
    - "No lymphadenopathy. No pleural effusion."
    - "The kidneys and adrenal glands demonstrate no focal abnormality."
  
  KEY PRINCIPLE: Balance between completeness and efficiency""",
                'comprehensive': """NEGATIVE FINDINGS - COMPREHENSIVE:
  STRUCTURE: Explicit statement for every anatomical system reviewed
  PRINCIPLE: Complete documentation of all normals, regardless of clinical relevance
  SEQUENCE: Systematic coverage of all systems imaged
  
  EXAMPLES:
    - "No consolidation, effusion, or pneumothorax. Normal cardiac size and contour. No mediastinal lymphadenopathy. Liver normal. Spleen normal. Kidneys demonstrate no focal abnormality."
  
  KEY PRINCIPLE: Complete documentation takes priority over efficiency
  USE CASE: Screening studies, teaching files, medico-legal documentation"""
            }
            if negative_style == 'distributed':
                negative_style = 'comprehensive'
            guidance_parts.append(negative_guidance.get(negative_style, negative_guidance['grouped']))
        
        # DESCRIPTOR DENSITY
        descriptor = advanced.get('descriptor_density', 'standard')
        if descriptor == 'sparse':
            guidance_parts.append("""
DESCRIPTOR DENSITY - SPARSE:
  - Use MINIMAL adjectives and descriptors
  - Include ONLY essential descriptive words
  - Omit shape, margins, enhancement patterns unless critical
  - Focus on WHAT it is, not HOW it looks
  - Applies to POSITIVE FINDINGS ONLY (not negative findings or review structure)
  
  EXAMPLES: 'Mass in liver' | 'Nodule in lung' | 'Lesion in kidney'
  
  NOTE: This controls adjectives only, independent of writing style (sentence structure/length)
""")
        elif descriptor == 'rich':
            guidance_parts.append("""
DESCRIPTOR DENSITY - RICH:
  - Use COMPREHENSIVE adjectives and descriptors
  - Include shape, margins, enhancement patterns, internal characteristics
  - Add anatomical precision (segments, stations, regions)
  - Full morphological characterization
  - Applies to POSITIVE FINDINGS ONLY (not negative findings or review structure)
  
  EXAMPLES: 'Well-defined 4cm ovoid mass in segment 7 of the liver with smooth margins and homogeneous enhancement'
  
  NOTE: This controls adjectives only, independent of writing style (sentence structure/length)
""")
        else:  # standard
            guidance_parts.append("""
DESCRIPTOR DENSITY - STANDARD:
  - Use BALANCED adjectives and descriptors
  - Include key characteristics (size, basic shape/margins when relevant)
  - Omit excessive morphological detail
  - Standard NHS reporting level
  - Applies to POSITIVE FINDINGS ONLY (not negative findings or review structure)
  
  EXAMPLES: '4cm well-defined mass in liver' | '3cm spiculated nodule in right upper lobe'
  
  NOTE: This controls adjectives only, independent of writing style (sentence structure/length)
""")
        
        # PARAGRAPH GROUPING
        para_grouping = advanced.get('paragraph_grouping', 'by_finding')
        # Handle backward compatibility: map 'by_subsection' to 'by_region'
        if para_grouping == 'by_subsection':
            para_grouping = 'by_region'
        
        para_guidance = {
            'continuous': """PARAGRAPH GROUPING - CONTINUOUS:
  STRUCTURE: One or two long paragraphs for entire findings section
  PRINCIPLE: Flowing continuous prose without paragraph breaks
  SEQUENCE: All findings in continuous text, no visual separation
  
  EXAMPLE STRUCTURE:
    "There is a 4cm mass in the right upper lobe. No mediastinal lymphadenopathy. The liver, spleen and pancreas are unremarkable. Small renal cyst noted."
  
  KEY PRINCIPLE: Single flowing narrative, no paragraph breaks
  USE CASE: Brief reports, rapid dictation""",
            
            'by_finding': """PARAGRAPH GROUPING - BY FINDING:
  STRUCTURE: Each significant finding or related group gets its own paragraph
  PRINCIPLE: Break into digestible paragraphs for enhanced readability
  SEQUENCE: Logical groupings by related anatomy or findings
  
  EXAMPLE STRUCTURE:
    "There is a 4cm spiculated mass in the right upper lobe, highly suspicious for malignancy. No mediastinal lymphadenopathy is identified.
    
    The liver, spleen and pancreas are unremarkable.
    
    Incidental note is made of a small renal cyst."
  
  KEY PRINCIPLE: Paragraph breaks enhance readability, group related findings
  USE CASE: Standard reporting, most common approach""",
            
            'by_region': """PARAGRAPH GROUPING - BY ANATOMICAL REGION:
  STRUCTURE: Separate paragraph for each major anatomical region/system
  PRINCIPLE: Clear visual separation between anatomical systems
  SEQUENCE: Each paragraph = one anatomical region/system
  
  EXAMPLE STRUCTURE:
    "There is a 4cm spiculated mass in the right upper lobe. No mediastinal lymphadenopathy. No pleural effusion.
    
    The liver, spleen and pancreas are unremarkable. No ascites.
    
    Normal pelvic appearance. Small renal cyst noted."
  
  KEY PRINCIPLE: Anatomical organization with clear regional separation via paragraph breaks
  USE CASE: Multi-region studies, systematic documentation
  NOTE: This works WITH organization settings - if organization is "systematic", this aligns naturally. Do NOT add headers or colons - use paragraph breaks only."""
        }
        guidance_parts.append(para_guidance.get(para_grouping, para_guidance['by_finding']))
        
        # FORMAT (presentation style)
        format_style = advanced.get('format', 'prose')
        format_guidance = {
            'prose': """FORMAT - FLOWING PROSE:
  - Paragraph-based narrative structure
  - Traditional medical prose style
  - Continuous sentences forming paragraphs
  - Use case: Standard reporting, most common""",
            
            'bullets': """FORMAT - BULLET POINTS:
  - Use bullet points for each discrete finding
  - Each point = one observation
  - Example:
    • 4cm mass in RUL
    • No lymphadenopathy
    • Small pleural effusion
  - Use case: Rapid reporting, structured lists"""
        }
        guidance_parts.append(format_guidance.get(format_style, format_guidance['prose']))
        
        # SUBSECTION HEADERS (standalone, can combine with any format)
        use_headers = advanced.get('use_subsection_headers', False)
        if use_headers:
            guidance_parts.append("""SUBSECTION HEADERS - ENABLED:
  - Use explicit anatomical region headers in CAPS (e.g., "CHEST:", "ABDOMEN:", "PLEURA:")
  - Blank line before each header
  - Headers followed by content in the selected format (prose/bullets/mixed)
  - Example with prose:
    CHEST WALL:
    No fracture. Soft tissues unremarkable.
    
    LUNGS:
    4cm spiculated mass in RUL. Otherwise clear.
    
    PLEURA:
    Small right pleural effusion.
  - Example with bullets:
    CHEST WALL:
    • No fracture
    • Soft tissues unremarkable
    
    LUNGS:
    • 4cm spiculated mass in RUL
    • Otherwise clear
  - Use case: Structured reports, multi-region studies, teaching files, enhanced readability""")
        
        return "\n\n".join(guidance_parts)
    
    def _build_impression_prompt_with_structured_evaluation(
        self,
        clinical_history: str,
        advanced: dict,
        recommendations_config: dict,
        custom_instructions: str = ''
    ) -> str:
        """
        Build impression prompt with stepwise evaluation workflow.
        Uses conditional language injection and directive boundaries.
        
        This replaces the old flat structure with:
        - Step 1A: Incidental findings evaluation (conditional)
        - Step 1B: Recommendations assessment (conditional)
        - Step 2: Generation with Tier 1 (mandatory) vs Tier 2 (style) hierarchy
        
        Args:
            clinical_history: Clinical question from patient history
            advanced: Advanced impression config (verbosity, format, etc.)
            recommendations_config: Dict of enabled recommendation types
            custom_instructions: Optional custom instructions
            
        Returns:
            Complete prompt string with structured evaluation workflow
        """
        prompt_parts = []
        
        # === HEADER ===
        prompt_parts.append(
            "=== STRUCTURED EVALUATION & GENERATION WORKFLOW ===\n"
            "\n"
            "Complete Steps 1A-1B (evaluation), then Step 2 (generation).\n"
            "\n"
            f"**Clinical Question** (from history):\n{clinical_history}"
        )
        
        # === STEP 1A: INCIDENTAL FINDINGS FILTER ===
        incidental_mode = advanced.get('incidental_handling', 'action_threshold')
        
        if incidental_mode == 'action_threshold':
            prompt_parts.append("""
**STEP 1A: ACTIONABLE INCIDENTAL FILTER**

Before generating impression, evaluate ALL incidental findings against clinical action criteria.

FOR EACH incidental finding in the report, apply this decision rubric:

1. CLINICAL ACTION TEST:
   Q: Does this finding require ANY specific action?
   - Specific follow-up imaging (with timeline)?
   - Specialist referral?
   - Further workup (biopsy, labs)?
   - Change in management?
   → If YES to any: INCLUDE in impression
   → If NO to all: Continue to Test 2

2. MALIGNANT POTENTIAL TEST:
   Q: Does this finding have concerning features?
   - Malignant potential (even if low risk)?
   - Indeterminate features requiring characterization?
   - Size/characteristics above reporting thresholds (e.g., lung nodule >6mm)?
   → If YES to any: INCLUDE in impression
   → If NO to all: Continue to Test 3

3. ESTABLISHED BENIGN PATTERN TEST:
   Q: Does this match an established benign pattern requiring NO action?
   
   BENIGN PATTERNS (omit if failing Tests 1 & 2):
   ✗ Simple cysts (renal, hepatic, ovarian): thin wall, no enhancement, water density
   ✗ Hepatic steatosis: diffuse pattern, no focal lesion
   ✗ Asymptomatic gallstones: if known and not causing obstruction
   ✗ Age-appropriate degenerative changes: no instability or nerve compression
   ✗ Atherosclerotic calcification: if not causing stenosis
   ✗ Calcified granulomas: if stable pattern
   
   → If YES (established benign) AND failed Tests 1 & 2: EXCLUDE from impression

DECISION OUTPUT: Create a list of incidental findings to INCLUDE vs EXCLUDE.""")
        
        elif incidental_mode == 'comprehensive':
            prompt_parts.append("""
**STEP 1A: INCIDENTAL FINDINGS** (Comprehensive mode active)

Include ALL incidental findings identified in the report, regardless of clinical significance.
Document both significant and minor incidental findings with appropriate language to indicate relative importance.""")
        
        elif incidental_mode == 'omit':
            prompt_parts.append("""
**STEP 1A: INCIDENTAL FINDINGS** (Omit mode active)

Do NOT include any incidental findings in the impression.
Focus exclusively on findings that address the primary clinical question.
Incidentals should remain in the Findings section only.""")
        
        # === STEP 1B: RECOMMENDATIONS ASSESSMENT ===
        enabled_recs = {k: v for k, v in recommendations_config.items() if v}
        
        if enabled_recs:
            rec_parts = ["""
**STEP 1B: RECOMMENDATIONS ASSESSMENT** (Independent evaluation - not affected by verbosity)

For each enabled criterion, evaluate whether findings warrant a specific recommendation:
"""]
            
            if enabled_recs.get('specialist_referral'):
                rec_parts.append("""
SPECIALIST REFERRAL
When do findings warrant specialist consultation?
- Urgent/concerning findings requiring immediate specialist input
- Complex findings needing subspecialty expertise
- Surgical/interventional findings requiring procedural planning

→ If warranted: Include specific specialty and urgency level
   Example: "Urgent respiratory review for massive pulmonary embolism with RV strain"
""")
            
            if enabled_recs.get('further_workup'):
                rec_parts.append("""
FURTHER WORK-UP
When are additional investigations needed?
- Alternative imaging modality would clarify findings
- Tissue diagnosis would guide management
- Laboratory tests would contextualize findings

→ If warranted: Include specific test/modality and rationale
   Example: "PET-CT for staging of lung mass"
""")
            
            if enabled_recs.get('imaging_followup'):
                rec_parts.append("""
IMAGING FOLLOW-UP
When is interval imaging appropriate?
- Indeterminate findings requiring stability assessment
- Known findings with surveillance protocols
- Size/characteristics warranting interval monitoring

→ If warranted: Include modality, timeframe, and indication
   Example: "CT chest in 3 months to assess 8mm nodule"
""")
            
            if enabled_recs.get('clinical_correlation'):
                rec_parts.append("""
CLINICAL CORRELATION
When do findings require clinical/laboratory correlation?
- Imaging findings need symptom correlation
- Abnormalities require specific lab correlation
- Findings need clinical examination context

→ If warranted: Be specific about which tests/parameters
   Example: "Correlate with troponin and BNP for RV strain assessment"
   Avoid generic: "Clinical correlation advised"
""")
            
            rec_parts.append("""
DECISION OUTPUT:
List applicable recommendations with specific wording.
Aim for actionable, specific language that guides the referring clinician.

CRITICAL: These recommendations are MANDATORY if warranted - they override verbosity settings.""")
            
            prompt_parts.append("\n".join(rec_parts))
        else:
            prompt_parts.append("""
**STEP 1B: RECOMMENDATIONS** (All recommendation criteria disabled)

Do NOT include recommendations in the impression.""")
        
        # === STEP 2: GENERATION WITH TIER SYSTEM ===
        step2_parts = ["""
**STEP 2: GENERATE IMPRESSION**

Now generate the impression using:

INPUT DATA:
- Primary findings addressing clinical question: """ + clinical_history + """
- Incidental findings list (from Step 1A evaluation)
- Recommendations list (from Step 1B evaluation)

OUTPUT REQUIREMENTS:

TIER 1 - MANDATORY CONTENT (include regardless of style):"""]
        
        # Build Tier 1 content list
        tier1_items = ["✓ Diagnostic conclusions for primary findings"]
        
        if incidental_mode == 'action_threshold':
            tier1_items.append("✓ Incidental findings from Step 1A (per action_threshold filter)")
        elif incidental_mode == 'comprehensive':
            tier1_items.append("✓ ALL incidental findings (comprehensive mode)")
        
        if enabled_recs:
            tier1_items.append(
                "✓ ALL recommendations identified in Step 1B\n"
                "  → These are clinical requirements, not stylistic choices\n"
                "  → Include even if verbosity=brief"
            )
        
        step2_parts.append("\n".join(tier1_items))
        
        # Build Tier 2 - Style guidance
        step2_parts.append("\nTIER 2 - STYLE APPLICATION (controls HOW to express Tier 1 content):\n")
        
        # Get style guidance from existing method (reuse the logic)
        style_guidance = self._build_tier2_style_guidance(advanced)
        step2_parts.append(style_guidance)
        
        # Add critical sequencing reminder
        step2_parts.append("""
CRITICAL SEQUENCING:
1. First, ensure ALL Tier 1 content is present
2. Then, apply Tier 2 style preferences to expression
3. Style preferences do NOT remove Tier 1 content - they only control phrasing/structure

**COMMITMENT TO DIAGNOSIS**:
- When imaging findings are definitive, state diagnosis directly using definitive language
- Use definitive statements (e.g., "X is present", "Y demonstrates Z") rather than hedging when evidence is clear
- Reserve uncertainty language ("consistent with", "suspicious for") only when findings are truly non-specific

**NO SEPARATE SECTIONS**:
- The impression section must contain ALL diagnostic conclusions, recommendations, and follow-up guidance within a single unified section
- DO NOT create separate sections such as "Recommendations", "Plan", "Follow-up", "Management"
- All recommendations and guidance must be integrated into the impression text itself""")
        
        prompt_parts.append("\n".join(step2_parts))
        
        # Add custom instructions if provided
        if custom_instructions and custom_instructions.strip():
            prompt_parts.append(f"\n**Custom Instructions**: {custom_instructions}")
        
        return "\n\n".join(prompt_parts)
    
    def _build_tier2_style_guidance(self, advanced: dict) -> str:
        """
        Build Tier 2 style guidance (verbosity, format, differential, etc.)
        Extracted from old _build_impression_style_guidance for reuse.
        """
        guidance_parts = []
        
        # Verbosity style
        verbosity_style = advanced.get('verbosity_style', 'prose')
        
        # Backward compatibility: map old values
        if verbosity_style == 'standard':
            verbosity_style = 'prose'
        elif verbosity_style == 'detailed':
            verbosity_style = 'prose'
        
        verbosity_map = {
            'brief': (
                "VERBOSITY STYLE: Brief\n"
                "\n"
                "Terse, direct phrasing:\n"
                "- Strip to essential wording\n"
                "- Minimal elaboration\n"
                "- Example: 'Acute appendicitis. No perforation or abscess.'\n"
                "\n"
                "Transform verbose phrasing:\n"
                "✗ 'Acute appendicitis is present without evidence of perforation'\n"
                "✓ 'Acute appendicitis. No perforation.'"
            ),
            'prose': (
                "VERBOSITY STYLE: Prose\n"
                "\n"
                "Balanced sentence structure with natural medical prose:\n"
                "- Primary diagnosis with confidence level when uncertain\n"
                "- Basic morphological descriptors when relevant\n"
                "- Standard NHS reporting style\n"
                "- Example: 'There is a spiculated mass in the right upper lobe, highly suspicious for primary lung malignancy.'"
            )
        }
        guidance_parts.append(verbosity_map.get(verbosity_style, verbosity_map['prose']))
        
        # Impression format (frontend sends 'format', legacy uses 'impression_format')
        impression_format = advanced.get('format') or advanced.get('impression_format', 'prose')
        format_map = {
            'prose': "FORMAT: Flowing prose sentences\n- Natural narrative structure",
            'bullets': "FORMAT: Bullet points\n- Each bullet = one key finding/conclusion\n- Use bullet symbol (•)",
            'numbered': "FORMAT: Numbered list\n- Numbered items (1., 2., etc.)"
        }
        guidance_parts.append(format_map.get(impression_format, format_map['prose']))
        
        # Differential (frontend sends 'differential_approach' with none/if_needed/always; legacy uses 'differential_style')
        diff_raw = advanced.get('differential_approach') or advanced.get('differential_style', 'if_needed')
        differential_style = 'always_brief' if diff_raw == 'always' else diff_raw
        differential_map = {
            'none': "DIFFERENTIAL DIAGNOSIS:\n- Do NOT include differential diagnosis\n- State primary diagnosis only",
            'if_needed': "DIFFERENTIAL DIAGNOSIS:\n- Include differential ONLY when diagnosis is uncertain or findings are non-specific\n- Provide 2-3 most likely alternatives with reasoning when needed\n- Skip if diagnosis is clear and definitive",
            'always': "DIFFERENTIAL DIAGNOSIS:\n- ALWAYS include 2-3 top differential diagnoses\n- Brief mention with most likely listed first",
            'always_brief': "DIFFERENTIAL DIAGNOSIS:\n- ALWAYS include 2-3 top differential diagnoses\n- Brief mention with most likely listed first",
            'always_detailed': "DIFFERENTIAL DIAGNOSIS:\n- ALWAYS include comprehensive differential diagnosis\n- List 3-5 possibilities with clinical reasoning for each\n- Discuss distinguishing features and supporting/contradicting findings"
        }
        guidance_parts.append(differential_map.get(differential_style, differential_map['if_needed']))
        
        # Comparison terminology
        comparison = advanced.get('comparison_terminology', 'measured')
        if comparison == 'conservative':
            comparison = 'simple'
        elif comparison == 'explicit':
            comparison = 'dated'
        
        comparison_map = {
            'simple': "COMPARISON TERMS:\n- Use descriptive terms: 'larger', 'smaller', 'stable', 'new', 'resolved'\n- No measurements or dates",
            'measured': "COMPARISON TERMS:\n- Include prior and current measurements when comparing\n- Example: 'increased from 3.2cm to 4cm'",
            'dated': "COMPARISON TERMS:\n- Include specific dates of prior studies\n- Include measurements and explicit temporal references"
        }
        guidance_parts.append(comparison_map.get(comparison, comparison_map['measured']))
        
        # Measurement inclusion
        measurements = advanced.get('measurement_inclusion', 'key_only')
        if measurements == 'none':
            guidance_parts.append("MEASUREMENTS:\n- Omit measurements from impression\n- Focus on diagnostic interpretation only")
        elif measurements == 'full':
            guidance_parts.append("MEASUREMENTS:\n- Repeat critical measurements\n- Include size for all significant findings")
        else:  # key_only
            guidance_parts.append("MEASUREMENTS:\n- Include key measurements for significant findings only\n- Example: '4cm mass' but not every dimension")
        
        return "\n\n".join(guidance_parts)
    
    def _build_impression_style_guidance(self, advanced: dict) -> str:
        """
        DEPRECATED: This method is no longer used.
        
        Use _build_impression_prompt_with_structured_evaluation() instead,
        which provides structured evaluation workflow with Tier 1/Tier 2 hierarchy.
        
        This method is kept for backward compatibility only.
        
        Generate IMPRESSION-specific style guidance (old flat structure)
        """
        guidance_parts = []
        
        # Verbosity style (replaces old numeric verbosity)
        verbosity_style = advanced.get('verbosity_style', 'prose')
        
        # Backward compatibility: map old values
        if verbosity_style == 'standard':
            verbosity_style = 'prose'
        elif verbosity_style == 'detailed':
            verbosity_style = 'prose'
        
        verbosity_map = {
            'brief': (
                "VERBOSITY STYLE: Brief\n"
                "\n"
                "HOW TO EXPRESS:\n"
                "  - Direct, concise diagnostic statements\n"
                "  - Minimal adjectives (only if essential for diagnosis)\n"
                "  - Eliminate filler words and verbose phrasing\n"
                "  - Think: corridor conversation between consultants\n"
                "\n"
                "GOOD EXAMPLES:\n"
                "  - 'Right upper lobe lung mass.'\n"
                "  - '4cm right upper lobe mass.' (with measurements)\n"
                "  - 'No acute intracranial abnormality.'\n"
                "  - '4cm right upper lobe mass. Recommend CT chest staging.' (with recommendations)\n"
                "\n"
                "BAD EXAMPLES:\n"
                "  - 'There is a spiculated mass located in the right upper lobe which appears suspicious...'\n"
                "  - 'The scan demonstrates no evidence of acute intracranial abnormality with normal brain parenchyma...'"
            ),
            'prose': (
                "VERBOSITY STYLE: Prose\n"
                "\n"
                "HOW TO EXPRESS:\n"
                "  - Balanced sentence structure with natural medical prose\n"
                "  - Primary diagnosis with confidence level when uncertain ('highly suspicious for', 'consistent with')\n"
                "  - Basic morphological descriptors when relevant\n"
                "  - Standard NHS reporting style\n"
                "\n"
                "STRUCTURE:\n"
                "  - Main finding with clinical impression\n"
                "  - Significant secondary findings (if present)\n"
                "  - Recommendations/differential as configured\n"
                "\n"
                "GOOD EXAMPLE:\n"
                "  'There is a spiculated mass in the right upper lobe, highly suspicious for primary lung\n"
                "   malignancy. A small right pleural effusion is present.'"
            )
        }
        guidance_parts.append(verbosity_map.get(verbosity_style, verbosity_map['prose']))
        
        # Impression format (frontend sends 'format', legacy uses 'impression_format')
        impression_format = advanced.get('format') or advanced.get('impression_format', 'prose')
        format_map = {
            'prose': "FORMAT: Flowing prose sentences\n  - Natural narrative structure\n  - Traditional medical prose style",
            'bullets': "FORMAT: Bullet points\n  - Each bullet = one key finding/conclusion\n  - Use bullet symbol (•) for each point",
            'numbered': "FORMAT: Numbered list\n  - Numbered items (1., 2., etc.)\n  - Clear sequential structure"
        }
        guidance_parts.append(format_map.get(impression_format, format_map['prose']))
        
        # Differential (frontend sends 'differential_approach' with none/if_needed/always; legacy uses 'differential_style')
        diff_raw = advanced.get('differential_approach') or advanced.get('differential_style', 'if_needed')
        differential_style = 'always_brief' if diff_raw == 'always' else diff_raw
        differential_map = {
            'none': "DIFFERENTIAL DIAGNOSIS:\n  - Do NOT include differential diagnosis\n  - State primary diagnosis only",
            'if_needed': "DIFFERENTIAL DIAGNOSIS:\n  - Include differential ONLY when diagnosis is uncertain or findings are non-specific\n  - Provide 2-3 most likely alternatives with reasoning when needed\n  - Skip if diagnosis is clear and definitive",
            'always': "DIFFERENTIAL DIAGNOSIS:\n  - ALWAYS include 2-3 top differential diagnoses\n  - Brief mention with most likely listed first\n  - Consider imaging findings and clinical context",
            'always_brief': "DIFFERENTIAL DIAGNOSIS:\n  - ALWAYS include 2-3 top differential diagnoses\n  - Brief mention with most likely listed first\n  - Consider imaging findings and clinical context",
            'always_detailed': "DIFFERENTIAL DIAGNOSIS:\n  - ALWAYS include comprehensive differential diagnosis\n  - List 3-5 possibilities with clinical reasoning for each\n  - Discuss distinguishing features and supporting/contradicting findings\n  - Order by likelihood based on imaging features"
        }
        guidance_parts.append(differential_map.get(differential_style, differential_map['if_needed']))
        
        # Comparison terminology
        comparison = advanced.get('comparison_terminology', 'measured')
        comparison_map = {
            'simple': "COMPARISON TERMS:\n  - Use descriptive terms only: 'larger', 'smaller', 'stable', 'new', 'resolved'\n  - No measurements or dates\n  - Example: 'larger than previously', 'stable compared to prior study'",
            'measured': "COMPARISON TERMS:\n  - Include prior and current measurements when comparing\n  - Use specific size changes\n  - Example: 'increased from 3.2cm to 4cm', 'decreased from 5cm to 3.5cm'",
            'dated': "COMPARISON TERMS:\n  - Include specific dates of prior studies\n  - Include measurements and explicit temporal references\n  - Example: 'increased from 3.2cm (15/01/2025) to 4cm on current study'"
        }
        # Backward compatibility
        if comparison == 'conservative':
            comparison = 'simple'
        elif comparison == 'explicit':
            comparison = 'dated'
        guidance_parts.append(comparison_map.get(comparison, comparison_map['measured']))
        
        # Measurement inclusion
        measurements = advanced.get('measurement_inclusion', 'key_only')
        if measurements == 'none':
            guidance_parts.append("MEASUREMENTS:\n  - Omit measurements from impression\n  - Focus on diagnostic interpretation only")
        elif measurements == 'full':
            guidance_parts.append("MEASUREMENTS:\n  - Repeat critical measurements\n  - Include size for all significant findings")
        else:  # key_only
            guidance_parts.append("MEASUREMENTS:\n  - Include key measurements for significant findings only\n  - Example: '4cm mass' but not every dimension")
        
        # Incidental handling
        incidentals = advanced.get('incidental_handling', 'action_threshold')
        if incidentals == 'omit':
            guidance_parts.append(
                "INCIDENTAL FINDINGS:\n"
                "  - Do NOT include any incidental findings in the impression\n"
                "  - Focus exclusively on findings that address the primary clinical question\n"
                "  - Incidentals should remain in the Findings section only\n"
                "  - This approach is for focused, targeted reporting"
            )
        elif incidentals == 'comprehensive':
            guidance_parts.append(
                "INCIDENTAL FINDINGS:\n"
                "  - Include ALL incidental findings in the impression, regardless of clinical significance\n"
                "  - Document both significant and minor incidental findings\n"
                "  - Provide comprehensive coverage of all findings identified\n"
                "  - Use appropriate language to indicate relative importance (e.g., 'Incidental note is made of...')"
            )
        else:  # action_threshold
            guidance_parts.append(
                "INCIDENTAL FINDINGS (Include if actionable):\n"
                "  - Include incidental findings ONLY if they meet actionable criteria:\n"
                "    • Requires specific follow-up imaging.\n"
                "    • Has malignant potential or concerning features\n"
                "    • Needs specialist referral or further investigation\n"
                "    • Requires intervention or specific clinical action\n"
                "  - OMIT incidental findings that are:\n"
                "    • Benign and common (e.g., simple renal cysts, degenerative changes)\n"
                "    • Below action thresholds (e.g., tiny nodules not warranting follow-up)\n"
                "    • Require no specific follow-up or intervention\n"
                "  - Decision rule: If the finding doesn't change immediate management or require specific action, omit from impression"
            )
        
        return "\n\n".join(guidance_parts)
    
    def _build_impression_recommendations_guidance(self, recommendations_config: dict) -> str:
        """
        DEPRECATED: This method is no longer used.
        
        Use _build_impression_prompt_with_structured_evaluation() instead,
        which integrates recommendations as Step 1B with MANDATORY criteria evaluation.
        
        This method is kept for backward compatibility only.
        
        Generate recommendation guidance from multi-checkbox config (old flat structure)
        """
        guidance = []
        
        if recommendations_config.get('specialist_referral'):
            guidance.append(
                "- Specialist Referral: If findings warrant specialist input, recommend "
                "appropriate referral with urgency when applicable (e.g., 'Neurosurgical review', "
                "'Urgent oncology consultation', 'Respiratory assessment')"
            )
        
        if recommendations_config.get('further_workup'):
            guidance.append(
                "- Further Work-up: If additional investigations would be beneficial, recommend "
                "alternative imaging, biopsy, procedures, or tests (e.g., 'PET-CT for staging', "
                "'Image-guided biopsy', 'Ultrasound assessment', 'Tissue diagnosis')"
            )
        
        if recommendations_config.get('imaging_followup'):
            guidance.append(
                "- Imaging Follow-up: If appropriate, include follow-up imaging with "
                "specific modality and timeframe (e.g., 'CT chest in 3 months', 'Repeat MRI in 6 months')"
            )
        
        if recommendations_config.get('clinical_correlation'):
            guidance.append(
                "- Clinical Correlation: If findings require clinical context, recommend "
                "correlation with SPECIFIC clinical parameters or laboratory tests. "
                "BE SPECIFIC - state which exact tests or assessments would be helpful. "
                "AVOID vague statements like 'clinical correlation advised'. "
                "Examples: 'Correlate with liver function tests (LFTs)', "
                "'Check renal function and electrolytes', "
                "'Assess for symptoms of hypercalcemia', "
                "'Review thyroid function tests', "
                "'Clinical examination for lymphadenopathy', "
                "'Correlate with inflammatory markers (CRP, ESR)', "
                "'Check serum calcium and PTH levels'"
            )
        
        if not guidance:
            return "- Do NOT include any recommendations"
        
        preamble = (
            "RECOMMENDATIONS (include if clinically appropriate - be specific, avoid generic phrases):\n"
        )
        return preamble + "\n".join(guidance)
    
    # ========================================================================
    # Content-Style-Specific Prompt Builders for FINDINGS
    # ========================================================================
    
    def _build_findings_prompt_normal_template(
        self, 
        template_content: str, 
        findings_input: str,
        advanced: dict
    ) -> str:
        """
        For 'normal_template' style: AI replaces relevant normal statements with abnormalities.
        Template contains complete normal report, user dictates only abnormalities.
        
        Style preferences extracted from advanced config metadata.
        """
        # Normalize config with defaults for backward compatibility
        advanced = self._normalize_advanced_config(advanced, section_type='findings')
        
        custom_instructions = advanced.get('instructions', '')
        
        organization = advanced.get('organization', 'clinical_priority')
        is_exact_order = organization == 'template_order'
        
        priority_reminder = (
            "**PRIORITY REMINDER**: Template structure takes precedence. The style settings below guide HOW to express findings, not WHAT structure to use."
            if is_exact_order else
            "**TEMPLATE ADAPTATION**: Emulate the template's language and content, but PRIORITIZE findings according to the organization style below."
        )
        
        anatomical_instr = (
            "- Maintain anatomical flow and organization from template"
            if is_exact_order else
            "- Apply organization style below (see ORGANIZATION guidance)\n- ANTI-DUPLICATION: Each structure mentioned ONCE only\n- If Clinical Priority: Lead with significant findings + immediate context, then return to template structure\n- When returning to template flow, skip any structures already addressed in priority section"
        )

        prompt = f"""
### FINDINGS SECTION - Normal Template Mode

{priority_reminder}

**Template**: Complete normal findings template provided below
**Your Task**: Replace ONLY the relevant normal statements with the abnormal findings dictated

**Normal Template**:
{template_content}

**User Dictated Abnormalities**:
{findings_input}

**Critical Instructions**:
- Keep all normal statements that are NOT contradicted by user findings
- Replace only the specific normal statements that relate to dictated abnormalities
{anatomical_instr}
- Do NOT add findings beyond what user dictated

**WRITING STYLE REQUIREMENTS**:

{self._build_detailed_style_guidance(advanced, section_type='findings', template_type='normal_template')}
"""
        
        if custom_instructions:
            prompt += f"\n\n**Custom Instructions**: {custom_instructions}"
        
        return prompt
    
    def _build_findings_prompt_guided_template(
        self, 
        template_content: str, 
        findings_input: str,
        advanced: dict
    ) -> str:
        """
        For 'guided_template' style: Template has content + // comment guidance.
        The prose defines report structure; // comments are contextual enrichers.
        Style preferences extracted from advanced config metadata.
        """
        # Normalize config with defaults for backward compatibility
        advanced = self._normalize_advanced_config(advanced, section_type='findings')
        
        custom_instructions = advanced.get('instructions', '')
        
        organization = advanced.get('organization', 'clinical_priority')
        is_exact_order = organization == 'template_order'
        
        # For guided templates, emphasize template structure preservation
        priority_reminder = (
            "**PRIORITY REMINDER**: Template structure takes precedence. The style settings below guide HOW to express findings, not WHAT structure to use."
            if is_exact_order else
            "**TEMPLATE STRUCTURE**: The prose defines your report structure and flow - follow this line by line. Style settings control HOW to express findings within this structure."
        )
        
        # Guided templates should maintain their structure - style settings refine expression, not organization
        anatomical_instr = (
            "- Follow the template's organizational flow line by line"
            if is_exact_order else
            "- Follow the template's prose structure line by line - it defines your organizational flow\n- Style settings (like Clinical Priority) control emphasis and expression WITHIN each section, not overall reorganization\n- ANTI-DUPLICATION: Each structure mentioned ONCE only\n- Replace normal statements with abnormal findings while maintaining the template's structural sequence"
        )

        prompt = f"""
### FINDINGS SECTION - Guided Prose Mode

{priority_reminder}

**Template Structure**: Prose statements (report structure) + // comment lines (contextual enrichers)

**Template**:
{template_content}

**User Dictated Findings**:
{findings_input}

**Critical Instructions**:
- The prose lines define your REPORT STRUCTURE - follow this organizational flow line by line
- Lines starting with '//' are CONTEXTUAL ENRICHERS - like a colleague's annotations explaining what each section assesses and providing principle-based guidance
- Replace normal prose statements with abnormal findings where applicable, but MAINTAIN the template's structural flow
- The // comments explain the assessment principles and coverage for each section - they are NOT output text
{anatomical_instr}

**WRITING STYLE REQUIREMENTS**:

{self._build_detailed_style_guidance(advanced, section_type='findings', template_type='guided_template')}
"""
        
        if custom_instructions:
            prompt += f"\n\n**Custom Instructions**: {custom_instructions}"
        
        return prompt
    
    def _build_findings_prompt_checklist(
        self, 
        template_content: str, 
        findings_input: str,
        advanced: dict
    ) -> str:
        """
        For 'checklist' style: Bullet point list to expand systematically.
        Style preferences extracted from advanced config metadata.
        """
        # Normalize config with defaults for backward compatibility
        advanced = self._normalize_advanced_config(advanced, section_type='findings')
        
        custom_instructions = advanced.get('instructions', '')
        
        organization = advanced.get('organization', 'clinical_priority')
        is_exact_order = organization == 'template_order'
        
        priority_reminder = (
            "**PRIORITY REMINDER**: Template structure takes precedence. The style settings below guide HOW to express findings, not WHAT structure to use."
            if is_exact_order else
            "**TEMPLATE ADAPTATION**: Emulate the template's language and content, but PRIORITIZE findings according to the organization style below."
        )
        
        anatomical_instr = (
            "- Systematically cover each anatomical structure in checklist"
            if is_exact_order else
            "- Apply organization style below (see ORGANIZATION guidance)\n- ANTI-DUPLICATION: Each structure mentioned ONCE only\n- If Clinical Priority: Lead with significant findings + immediate context, then return to template structure\n- When returning to template flow, skip any structures already addressed in priority section"
        )

        prompt = f"""
### FINDINGS SECTION - Checklist Mode

{priority_reminder}

**Checklist**:
{template_content}

**User Dictated Findings**:
{findings_input}

**Critical Instructions**:
{anatomical_instr}
- Integrate user findings where relevant
- Report normal for structures not mentioned in user findings

**WRITING STYLE REQUIREMENTS**:

{self._build_detailed_style_guidance(advanced, section_type='findings', template_type='checklist')}
"""
        
        if custom_instructions:
            prompt += f"\n\n**Custom Instructions**: {custom_instructions}"
        
        return prompt
    
    def _build_findings_prompt_headers(
        self, 
        template_content: str, 
        findings_input: str,
        advanced: dict
    ) -> str:
        """
        For 'headers' style: Section headers, AI fills content under each.
        Style preferences extracted from advanced config metadata.
        """
        # Normalize config with defaults for backward compatibility
        advanced = self._normalize_advanced_config(advanced, section_type='findings')
        
        custom_instructions = advanced.get('instructions', '')
        
        organization = advanced.get('organization', 'clinical_priority')
        is_exact_order = organization == 'template_order'
        
        priority_reminder = (
            "**PRIORITY REMINDER**: Template structure takes precedence. The style settings below guide HOW to express findings, not WHAT structure to use."
            if is_exact_order else
            "**TEMPLATE ADAPTATION**: Emulate the template's language and content, but PRIORITIZE findings according to the organization style below."
        )
        
        anatomical_instr = (
            "- Fill content under each header based on user findings\n- Leave headers in place, maintain their order"
            if is_exact_order else
            "- Fill content under each header based on user findings\n- Apply organization style below (see ORGANIZATION guidance)\n- ANTI-DUPLICATION: Each structure mentioned ONCE only\n- If Clinical Priority: Lead with significant findings + immediate context, then return to template structure\n- When returning to template flow, skip any structures already addressed in priority section"
        )

        prompt = f"""
### FINDINGS SECTION - Headers Mode

{priority_reminder}

**Headers Provided**:
{template_content}

**User Dictated Findings**:
{findings_input}

**Critical Instructions**:
{anatomical_instr}

**WRITING STYLE REQUIREMENTS**:

{self._build_detailed_style_guidance(advanced, section_type='findings', template_type='normal_template')}
"""
        
        if custom_instructions:
            prompt += f"\n\n**Custom Instructions**: {custom_instructions}"
        
        return prompt
    
    def _build_findings_prompt_structured_template(
        self,
        template_content: str,
        findings_input: str,
        advanced: dict = None
    ) -> str:
        """
        Build prompt for structured template style.
        Template structure is PRESERVED - AI fills in blanks only.
        """
        custom_instructions = advanced.get('instructions', '') if advanced else ''
        
        return f"""
### FINDINGS SECTION - Structured Fill-In Mode

**STRICT FIDELITY REQUIRED**: Preserve template structure with absolute precision.

**Structured Template** (PRESERVE EXACTLY):
```
{template_content}
```

**User Findings**:
{findings_input}

**PLACEHOLDER FILLING RULES**:

1. {{VAR}} placeholders:
   - Search user findings for variable name (e.g., {{LVEF}} → find "LVEF" or "ejection fraction")
   - Replace with exact value found
   - If NOT found in input → LEAVE AS {{VAR}} (do not fabricate)
   - **CRITICAL**: Do NOT replace {{VAR}} with phrases like "not specified", "not provided", "not measured"
   - The {{VAR}} placeholder must remain in output for post-processing detection

2. xxx measurements:
   - Replace with measurements from findings
   - If measurement not provided → LEAVE AS xxx EXACTLY (do not estimate)
   - **CRITICAL**: Do NOT replace xxx with phrases like "not specified", "not provided", "not measured"
   - The xxx placeholder must remain in output for post-processing detection
   - When a measurement is present in the input but not explicitly labelled or formatted to match the placeholder, apply clinical and contextual inference to determine whether the value can be unambiguously attributed to that placeholder. Consider the surrounding prose, the anatomical or physiological context, the units implied or expected, and the structure of the input as a whole. If attribution is unambiguous through this reasoning, extract and fill the placeholder. Only leave a placeholder unfilled if genuine ambiguity remains after contextual inference — not simply because the input phrasing does not directly mirror the placeholder syntax.
   
   UNIT HANDLING:
   When extracting a measurement to fill an xxx placeholder, the default action is always to fill. Apply the following in order:

   - If the value is present with explicit, matching units — fill directly.
   - If the value is present but units are absent or ambiguous — fill the numeric value unconditionally, append [units unconfirmed] immediately after the number, and preserve the template's expected unit label. Never leave a placeholder as xxx solely because units are missing or unconfirmed.
   - If the numeric value itself is genuinely absent or cannot be attributed to the placeholder through any contextual reasoning — only then leave as xxx.

   The threshold for leaving a placeholder unfilled is genuine absence of a numeric value, not absence of explicit units. Unit uncertainty is an annotation problem, not a filling problem.
   
   WRONG transformations to AVOID:
   ✗ "diameter xxx mm" → "diameter is not specified"
   ✗ "diameter xxx mm" → "diameter not provided"  
   ✗ "diameter xxx mm" → "diameter not measured"
   ✗ "measuring xxx mm" → "size not documented"
   
   CORRECT behavior:
   ✓ "diameter xxx mm" → "diameter xxx mm" (unchanged if no measurement)

3. [option1/option2] alternatives:
   - SELECT the most appropriate option based on findings
   - Remove brackets, keep selected option only
   - Example: "[normal/increased]" → "normal" or "increased"

4. // instructions:
   - Follow guidance during generation WHEN filling content
   - STRIP all // lines from final output (do not include in report)
   - IMPORTANT: // instructions guide HOW to describe WHEN input exists, NOT whether to include the section header

5. DETAIL AUGMENTATION:
   
   CORE PRINCIPLE:
   If user provides clinically significant details not captured by template structure,
   integrate them naturally into the most relevant template section.
   
   WHEN TO AUGMENT:
   ✓ Clinical modifiers that affect diagnosis/management
   ✓ Specific anatomical structures or distributions
   ✓ Additional measurements or characteristics
   ✗ Redundant information already in template
   ✗ Vague descriptions without clinical value
   ✗ Details contradicting template selections
   
   HOW TO INTEGRATE:
   
   Use natural medical prose connectors based on context:
   • "with" - for associated findings or characteristics
   • "and" - for additional co-existing features
   • "including" or "via" - for specifications or pathways
   • "in" - for locations or distributions
   • Parentheses - for clarifications or classifications
   
   When template already uses a connector, avoid repetition:
   • Template uses "with" + User adds "with" → Use "and" instead
   • Template uses "including" + User adds "including" → Combine the lists
   
   Keep augmentations concise (1-3 additional descriptors maximum).
   Maintain template's formal prose style.
   
   EXAMPLES (across systems):
   
   Cardiac:
   Template: "Left ventricle is dilated"
   User: "apical thrombus"
   → "Left ventricle is dilated with apical thrombus"
   
   Vascular:
   Template: "Origin is abnormal"
   User: "with thrombus"
   → "Origin is abnormal with thrombus"
   
   Template: "...with abnormal origin"
   User: "with thrombus"
   → "...with abnormal origin and thrombus"
   
   Template: "Collateral vessels are present"
   User: "arc of Riolan, marginal artery"
   → "Collateral vessels are present via arc of Riolan and marginal artery"
   
   MSK:
   Template: "Fracture is present"
   User: "displaced, comminuted, involves articular surface"
   → "Fracture is present with displacement and comminution involving articular surface"
   
   Neuro:
   Template: "Mass is present"
   User: "left frontal with mass effect"
   → "Mass is present in left frontal lobe with mass effect"
   
   Default: When uncertain about integration, prioritize template fidelity

6. CONFLICT RESOLUTION:
   Before finalising any filled section, check that all elements within it are mutually consistent. If an augmentation, additional finding, or user input contradicts the template default selection or sentence, the default must be modified or replaced — not preserved alongside the contradiction.
   Specifically:

   - If a [option1/option2] selection is contradicted by a finding you are also documenting in the same section, revise the selection to be consistent with that finding, or restructure the sentence so no contradiction exists.
   - If the template default sentence asserts a normal or neutral state that is directly incompatible with user input, replace that sentence rather than appending to it. Appending is appropriate only when the additional finding coexists with, rather than contradicts, the default state.
   - If user input contains measurements or values that can be unambiguously attributed to a placeholder through clinical context — even without explicit labelling — extract and fill them. Do not leave a placeholder unfilled solely because the input uses informal phrasing, provided the attribution is clinically unambiguous.

   Contradiction takes priority over template fidelity. An internally inconsistent section is always a greater error than a deviation from template wording.

7. BLANK SECTIONS (no corresponding input):
   - **CRITICAL RULE**: ALL section headers MUST be preserved in output, regardless of // instructions
   - **IMPORTANT DISTINCTION**:
     • If template has alternatives like [present/absent] or [normal/abnormal] AND user input indicates the negative state (e.g., "no LGE", "normal wall motion"):
       → FILL the section with the appropriate alternative (e.g., "absent", "normal")
       → Include the section header and filled content
       → Do NOT flag as //UNFILLED:
     • Only flag as //UNFILLED: if there is TRULY no information about that section in the user input
   - **EVEN IF** a // instruction says "only if X" or "describe only if abnormal":
     • If user input provides information (even if negative/normal), FILL the section appropriately with the correct alternative
     • Only flag as //UNFILLED: if no input provided at all
     • The // instruction guides HOW to describe WHEN input exists, not whether to include the section
   - **OUTPUT FORMAT FOR BLANK SECTIONS**:
     • When a section has no input, output ONLY: //UNFILLED: [SECTION_NAME]
     • **CRITICAL**: The //UNFILLED: marker MUST be on its own line (preceded by a newline, followed by a newline)
     • Do NOT include the section header line above it
     • Do NOT embed //UNFILLED: in the middle of sentences or paragraphs
     • Post-processing will handle highlighting and display
     • Example CORRECT format:
       ```
       Some previous content here.
       
       //UNFILLED: THROMBUS
       
       Next section content.
       ```
     • Example INCORRECT format (DO NOT DO THIS):
       ```
       Some text //UNFILLED: THROMBUS more text here.
       ```
   - Examples:
     ```
     // User input: "No LGE"
     // Template: "LGE is [present/absent]"
     // CORRECT OUTPUT:
     LATE GADOLINIUM ENHANCEMENT
     LGE is absent.
     
     // User input: (no mention of thrombus at all)
     // Template: "// Describe only if thrombus present\nTHROMBUS\n..."
     // CORRECT OUTPUT:
     //UNFILLED: THROMBUS
     
     // User input: (no mention of aorta)
     // Template: "AORTA\n..."
     // CORRECT OUTPUT:
     //UNFILLED: AORTA
     ```

**PLACEHOLDER PRESERVATION - CRITICAL**:

When a placeholder cannot be filled from user input:
- xxx measurements: LEAVE AS "xxx" - do not substitute explanatory text
- {{VAR}} variables: LEAVE AS "{{VAR}}" - do not substitute explanatory text

Post-processing will detect and highlight unfilled placeholders.
Your job is template filling, not explaining missing data.

Examples of WRONG behavior (do not do this):
✗ "diameter xxx mm" → "diameter is not specified"
✗ "LVEF {{LVEF}}%" → "LVEF not provided"
✗ "measuring xxx cm" → "size not documented"

Examples of CORRECT behavior:
✓ "diameter xxx mm" → "diameter xxx mm" (unchanged)
✓ "LVEF {{LVEF}}%" → "LVEF {{LVEF}}%" (unchanged)
✓ "measuring xxx cm" → "measuring xxx cm" (unchanged)

**CRITICAL FIDELITY RULES**:
- PRESERVE template structure and wording as much as possible
- FLEXIBILITY ALLOWED for:
  • Following // instruction guidance WHEN filling content (e.g., "// Describe only if abnormal" means describe abnormalities if present, but still flag section as UNFILLED if no input)
  • Adding appropriate descriptors when clinically relevant (e.g., "moderate" for a 40mm mass)
  • Minor grammatical adjustments for flow
- STRICT PRESERVATION required for:
  • Overall template structure and ALL section headers (never omit)
  • Core sentence structure and medical terminology
  • Placeholder syntax (until filled)
- NEVER fabricate measurements or findings not in user input
- NEVER fundamentally change the template's underlying format
- NEVER omit section headers, even if // instructions suggest conditional inclusion
- British English throughout

{f"**Additional Instructions**: {custom_instructions}" if custom_instructions else ""}

Generate the FINDINGS section now.
"""
    
    # ========================================================================
    # Hybrid Section Handler
    # ========================================================================
    
    def _build_hybrid_section_prompt(
        self, 
        section_name: str,
        section_config: dict,
        user_input: str,
        findings: str,
        scan_metadata: dict
    ) -> str:
        """
        Hybrid sections: wizard toggle determines manual input vs auto-generation.
        
        FRONTEND DATA FLOW (from Step3_SectionBuilder.svelte):
        - User toggles between "Manual input" and "Auto-generated"
        - has_input_field = True → Manual mode (textarea shown, user MUST provide value)
        - has_input_field = False → Auto-generation mode (no textarea, extract from data)
        
        When has_input_field = True (MANUAL):
            - User provides text → refine it
            - User leaves blank → omit section entirely
        
        When has_input_field = False (AUTO):
            - Extract from findings (COMPARISON, LIMITATIONS)
            - Generate from metadata (TECHNIQUE)
        """
        has_input_field = section_config.get('has_input_field', True)
        
        if has_input_field:
            # MANUAL INPUT MODE - user chose to manually input
            # User MUST provide a value - if empty, omit the section
            if user_input and user_input.strip():
                # User provided input - refine it
                return f"""
### {section_name} SECTION - Refine Manual Input

**User Input**:
{user_input}

**Task**: Refine into proper medical prose:
- Expand any abbreviations to full medical terms
- Fix grammar/vocabulary errors
- Convert shorthand notes to complete sentences
- Maintain user's intended meaning
- Keep concise and professional
"""
            else:
                # Manual mode but no input provided - omit section
                return f"""
### {section_name} SECTION - Omit

No user input provided. Omit this section entirely from output.
"""
        else:
            # AUTO-GENERATION MODE - extract from findings/metadata
            if section_name == "TECHNIQUE":
                scan_type = scan_metadata.get('scan_type', '')
                contrast = scan_metadata.get('contrast', '')
                protocol_details = scan_metadata.get('protocol_details', '')
                
                return f"""
### {section_name} SECTION - Auto-Generate from Metadata

**Scan Information**:
- Scan Type: {scan_type}
- Contrast: {contrast}
- Protocol: {protocol_details}

**Task**: Generate standard technique statement:
- Brief (1-2 sentences maximum)
- Standard radiology phrasing
- Include scan modality, body region, and contrast protocol if relevant
- Example format: "Non-contrast CT of the head performed on a 64-slice scanner"
"""
            elif section_name == "COMPARISON":
                return f"""
### {section_name} SECTION - Extract from Findings

**Findings Text**:
{findings}

**Task**: Extract comparison information from findings:
- Search for mentions of prior imaging/studies
- Keywords to look for: "previous", "prior", "comparison", "compared with", "stable", "unchanged", "interval", "as before"
- If found → Extract and format: "Compared with [modality] [region] [date if mentioned]"
- If NOT found → Output: "No previous imaging available for comparison"
- Keep to one concise sentence
"""
            elif section_name == "LIMITATIONS":
                return f"""
### {section_name} SECTION - Extract from Findings

**Findings Text**:
{findings}

**Task**: Extract technical limitations from findings:
- Search for limitation mentions in findings
- Keywords: "limited by", "degraded by", "suboptimal", "artifact", "motion", "incomplete", "technically difficult"
- If limitations found → Extract and state clearly in professional medical prose
- If NO limitations found → Omit this section entirely (do NOT output "None" or any text)
"""
        
        return ""
    
    # ========================================================================
    # Main Report Generation Method
    # ========================================================================
    
    async def generate_report_from_config(
        self,
        template_config: dict,
        user_inputs: dict,
        user_signature: str = None
    ) -> dict:
        """
        Generate report using structured config with section-aware prompt construction.
        Complete separation from legacy template system - builds prompts from scratch.
        
        Args:
            template_config: Structured configuration dict containing scan info and sections
            user_inputs: User-provided values for input fields (e.g., FINDINGS, CLINICAL_HISTORY)
            user_signature: Optional user signature to append
            
        Returns:
            Dict with report_content, description, scan_type
        """
        from pydantic import BaseModel
        from .enhancement_utils import (
            MODEL_CONFIG,
            _get_model_provider,
            _get_api_key_for_provider,
            _run_agent_with_model,
            _append_signature_to_report,
            _log_glm_reasoning,
            _generate_report_with_claude_model,
        )
        
        # Extract metadata
        scan_type = template_config.get('scan_type', '')
        contrast = template_config.get('contrast', '')
        protocol_details = template_config.get('protocol_details', '')
        global_custom_instructions = template_config.get('global_custom_instructions', '')
        sections_config = template_config.get('sections', [])
        clinical_history_config = template_config.get('clinical_history', {})
        
        # Check if clinical history should be included in output
        include_clinical_history_in_output = clinical_history_config.get('include_in_output', False)
        
        # Sort sections by order
        sorted_sections = sorted(sections_config, key=lambda s: s.get('order', 999))
        
        # Build section-specific prompts
        section_prompts = []
        template_structure = []  # For final template assembly
        
        findings_input = user_inputs.get('FINDINGS', '')
        clinical_history = user_inputs.get('CLINICAL_HISTORY', '')
        
        for section in sorted_sections:
            if not section.get('included', True):
                continue
                
            section_name = section.get('name', '')
            display_name = section.get('display_name', section_name)
            generation_mode = section.get('generation_mode', 'auto_generated')
            
            # Skip CLINICAL_HISTORY in template structure if include_in_output is False
            # (but still use it as context in prompts)
            if section_name == 'CLINICAL_HISTORY' and not include_clinical_history_in_output:
                # Still add prompt instruction but don't include in template structure
                section_prompts.append(f"""
**{section_name}**: Used as context only - DO NOT include in report output
""")
                continue
            
            # Build section header for template
            template_structure.append(f"{display_name}:")
            template_structure.append(f"{{{{{section_name}}}}}")
            template_structure.append("")
            
            # Build section-specific prompt instructions
            if generation_mode == 'passthrough':
                # CLINICAL_HISTORY - direct insertion (only if include_in_output is True)
                section_prompts.append(f"""
**{section_name}**: Direct passthrough - use user input verbatim
""")
                
            elif generation_mode == 'template_based':
                # FINDINGS - style-specific handling
                content_style = section.get('content_style', 'normal_template')
                template_content = section.get('template_content', '')
                advanced = section.get('advanced', {})
                style_templates = section.get('style_templates', {})
                style_body = style_templates.get(content_style, '') if isinstance(style_templates, dict) else ''
                if style_body and template_content != style_body:
                    logger.warning(
                        "template_content and style_templates[%s] differ for section %s — using template_content. Consider re-saving template.",
                        content_style,
                        section.get('name', 'FINDINGS'),
                    )
                # Get style-specific prompt - pass advanced config for style extraction
                if content_style == 'normal_template':
                    style_prompt = self._build_findings_prompt_normal_template(
                        template_content, findings_input, advanced
                    )
                elif content_style == 'guided_template':
                    style_prompt = self._build_findings_prompt_guided_template(
                        template_content, findings_input, advanced
                    )
                elif content_style == 'checklist':
                    style_prompt = self._build_findings_prompt_checklist(
                        template_content, findings_input, advanced
                    )
                elif content_style == 'headers':
                    style_prompt = self._build_findings_prompt_headers(
                        template_content, findings_input, advanced
                    )
                elif content_style == 'structured_template':
                    style_prompt = self._build_findings_prompt_structured_template(
                        template_content, findings_input, advanced
                    )
                else:
                    style_prompt = f"Generate FINDINGS section from: {findings_input}"
                
                section_prompts.append(style_prompt)
                
            elif generation_mode == 'hybrid':
                # COMPARISON, LIMITATIONS, TECHNIQUE
                # Section config contains has_input_field toggle
                user_section_input = user_inputs.get(section_name, '')
                
                # Pass full section config and scan metadata for intelligent handling
                scan_metadata = {
                    'scan_type': scan_type,
                    'contrast': contrast,
                    'protocol_details': protocol_details
                }
                
                hybrid_prompt = self._build_hybrid_section_prompt(
                    section_name,
                    section,  # Full section config with has_input_field
                    user_section_input,
                    findings_input,
                    scan_metadata
                )
                section_prompts.append(hybrid_prompt)
                
            elif generation_mode == 'auto_generated':
                # IMPRESSION - synthesis from all above
                # ALL style requirements come from advanced config
                advanced = section.get('advanced', {})
                
                # Normalize config with defaults for backward compatibility
                advanced = self._normalize_advanced_config(advanced, section_type='impression')
                
                custom_instructions = advanced.get('instructions', '')
                recommendations_config = advanced.get('recommendations', {})
                
                # Build comprehensive impression prompt with structured evaluation workflow
                impression_prompt = self._build_impression_prompt_with_structured_evaluation(
                    clinical_history=clinical_history,
                    advanced=advanced,
                    recommendations_config=recommendations_config,
                    custom_instructions=custom_instructions
                )
                
                section_prompts.append(impression_prompt)
        
        # Note: Signature will be appended in post-processing, not in template structure
        # This ensures clean separation and matches old function behavior
        
        # Assemble final template
        template_string = "\n".join(template_structure)
        
        # Build comprehensive section-specific instructions
        section_instructions = "\n\n".join(section_prompts)
        
        # Append global custom instructions if provided
        if global_custom_instructions:
            section_instructions += f"\n\n**Template-Wide Instructions (applied across all sections during generation)**: {global_custom_instructions}"
        
        # Build clinical history instruction text
        clinical_history_instruction = (
            "Include in report output" 
            if include_clinical_history_in_output 
            else "Use as context only - DO NOT include in report output"
        )
        
        # === BUILD PROMPTS FROM SCRATCH - NO LEGACY METHODS ===
        # Complete separation from old template system
        
        # Build system prompt
        system_prompt = f"""You are an expert NHS consultant radiologist. Generate professional radiology reports in British English following NHS standards.

CRITICAL: All output must use British English spelling and terminology.

OUTPUT FORMAT: Provide structured JSON with three fields:
- "report_content": Complete radiology report with proper formatting (line breaks between sections, paragraph structure)
- "description": Brief 5-15 word summary for history (max 150 chars, exclude scan type)
- "scan_type": Extract from context (e.g., "CT head non-contrast")

CORE PRINCIPLES:
- NO hallucination - include ONLY information from provided inputs
- NO duplication - each finding mentioned once only
- Protocol consistency - verify findings match scan type/protocol
- British English throughout
"""
        # Inject skill sheet if present — overrides generic style defaults
        skill_sheet = template_config.get("skill_sheet")
        if skill_sheet:
            system_prompt += f"""
## TEMPLATE SKILL SHEET
The following skill sheet defines the specific reporting conventions for this template. Follow these conventions precisely — they take precedence over generic style defaults:

{skill_sheet}
"""
        
        # Determine if any section is using "Exact" mode (structured_template)
        has_exact_mode = any(s.get('content_style') == 'structured_template' for s in sections_config)
        
        philosophy_instr = """
=== TEMPLATE PHILOSOPHY ===
This report contains "Flexible" and/or "Structured Fill-In" sections. 
- FLEXIBLE SECTIONS (Normal, Guided, Checklist, Headers): 
  • Template provides the organizational framework and style guide
  • User's style settings control HOW findings are organized and expressed
  • Each anatomical structure/finding mentioned ONCE only
  
- STRUCTURED FILL-IN SECTIONS: 
  • Preserve template structure and wording precisely
  • Fill placeholders following // instruction guidance
  • Minor grammatical adjustments for natural flow only
  • Do NOT fundamentally change core structure or terminology
""" if has_exact_mode else """
=== TEMPLATE PHILOSOPHY ===
All sections in this report are "Flexible".
- Template provides the organizational framework and style guide
- User's style settings control HOW findings are organized and expressed  
- Each anatomical structure/finding mentioned ONCE only
"""

        output_consistency_rule = """
=== OUTPUT CONSISTENCY RULE ===
Any section of the output that synthesises, summarises, or concludes from findings above it must remain faithful to the state of those findings. Specifically:

- A synthesising statement must NOT assert normality or completeness for any finding that remains unfilled, unresolved, or marked //UNFILLED: in the body above.
- A synthesising statement must NOT contradict or flatten any abnormality, augmentation, or pathological selection present in the body above.
- Where findings are partially documented, the synthesising statement must reflect that partial state rather than defaulting to either normality or abnormality.

This applies to any template section that draws on preceding content — whether labelled Summary, Conclusion, Impression, Assessment, or otherwise.
""" if has_exact_mode else ""

        system_prompt = system_prompt + output_consistency_rule

        # Build user prompt
        user_prompt = f"""Generate a radiology report for:

**SCAN TYPE**: {scan_type}
**CONTRAST**: {contrast}
**PROTOCOL**: {protocol_details}

{philosophy_instr}

=== INPUT DATA ===

**Clinical History**:
{clinical_history}

**Findings**:
{findings_input}

=== SECTION-SPECIFIC GENERATION INSTRUCTIONS ===

{section_instructions}

=== OUTPUT TEMPLATE STRUCTURE ===

{template_string}

=== GENERATION REQUIREMENTS ===

1. Follow each section's specific instructions above
2. Maintain section order as shown in template
3. Use proper formatting (double line breaks between sections)
4. Ensure report_content contains ONLY the report sections shown in template structure
5. Clinical History: {clinical_history_instruction}
6. Generate concise description for history tab
7. Extract accurate scan_type
8. NO DUPLICATION: Each anatomical structure/finding mentioned once only, regardless of organization method

Generate the report now as valid JSON.
"""
        
        # Generate report: primary zai-glm-4.7 (Cerebras), fallback claude-sonnet-4-6 (Anthropic)
        model_name = MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"]
        fallback_model = MODEL_CONFIG["FALLBACK_REPORT_GENERATOR"]  # claude-sonnet-4-20250514
        provider = _get_model_provider(model_name)
        api_key = _get_api_key_for_provider(provider)
        anthropic_api_key = None
        try:
            anthropic_api_key = _get_api_key_for_provider("anthropic")
        except ValueError:
            pass  # Anthropic not configured - fallback will not be available
        
        if not api_key:
            raise ValueError(f"API key not configured for provider: {provider}")
        
        class ReportOutput(BaseModel):
            report_content: str
            description: str
            scan_type: str
        
        try:
            # Try structured output first, fallback to string parsing if it fails
            try:
                result = await _run_agent_with_model(
                model_name=model_name,
                output_type=ReportOutput,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                use_thinking=True,  # Enable reasoning for gpt-oss models
                model_settings={
                    "temperature": 0.8,
                    "top_p": 0.95,
                    "max_tokens": 40960,
                    "extra_body": {
                        "disable_reasoning": False,
                        "clear_thinking": False,
                    },
                }
                )
                
                # Log GLM reasoning for debugging (same as quick report)
                _log_glm_reasoning(result, f"{model_name} (Template Report) - GLM Reasoning")
                
                # Don't append signature yet - will append after validation
                report_output = result.output
                
                # LINGUISTIC VALIDATION for zai-glm-4.7 (conditionally enabled)
                import os
                ENABLE_LINGUISTIC_VALIDATION = os.getenv("ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION", "true").lower() == "true"
                
                if ENABLE_LINGUISTIC_VALIDATION:
                    from .enhancement_utils import validate_template_linguistics
                    
                    try:
                        print(f"\n{'='*80}")
                        print(f"🔍 TEMPLATE LINGUISTIC VALIDATION - Starting")
                        print(f"{'='*80}")
                        
                        validated_content = await validate_template_linguistics(
                            report_content=report_output.report_content,
                            template_config=template_config,
                            user_inputs=user_inputs,
                            scan_type=report_output.scan_type
                        )
                        
                        report_output.report_content = validated_content
                        print(f"✅ TEMPLATE LINGUISTIC VALIDATION COMPLETE")
                        print(f"{'='*80}\n")
                    except Exception as e:
                        print(f"\n{'='*80}")
                        print(f"⚠️ TEMPLATE LINGUISTIC VALIDATION FAILED - continuing with original")
                        print(f"{'='*80}")
                        print(f"[ERROR] {type(e).__name__}: {str(e)[:300]}")
                        import traceback
                        print(f"[ERROR] Traceback:")
                        print(traceback.format_exc()[:500])
                        print(f"{'='*80}\n")
                else:
                    print(f"[DEBUG] Template linguistic validation disabled (ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION=false)")
                
                # Append signature AFTER validation (or if validation disabled)
                if user_signature:
                    report_output = _append_signature_to_report(report_output, user_signature)
                
                return {
                    "report_content": report_output.report_content,
                    "description": report_output.description,
                    "scan_type": report_output.scan_type,
                    "model_used": model_name,
                }
            except Exception as e:
                # Check if it's a structured output timeout/error
                error_str = str(e).lower()
                is_structured_output_error = (
                    'structured output' in error_str or
                    'response_format' in error_str or
                    'wrong_api_format' in error_str or
                    '422' in error_str or
                    'tool_choice' in error_str or
                    'tool_calls' in error_str
                )
                
                if is_structured_output_error:
                    print(f"[WARNING] Structured output failed for {model_name}, falling back to string output: {e}")
                    # Fallback: Use string output and parse JSON manually
                    try:
                        # Update prompt to explicitly request JSON format
                        json_prompt = user_prompt + "\n\nIMPORTANT: Return your response as a valid JSON object with keys: 'report_content', 'description', 'scan_type'."
                        
                        result = await _run_agent_with_model(
                            model_name=model_name,
                            output_type=str,
                            system_prompt=system_prompt,
                            user_prompt=json_prompt,
                            api_key=api_key,
                            use_thinking=False,  # Disable thinking for fallback
                            model_settings={
                                "temperature": 0.8,
                                "top_p": 0.95,
                                "max_tokens": 40960,
                                "extra_body": {
                                    "disable_reasoning": False,
                                    "clear_thinking": False,
                                },
                            }
                        )
                        
                        # Log GLM reasoning for debugging (same as quick report)
                        _log_glm_reasoning(result, f"{model_name} (Template Report Fallback) - GLM Reasoning")
                        
                        # Parse JSON from string response
                        import json
                        import re
                        
                        response_text = str(result.output).strip()
                        
                        # Try to extract JSON from response (handle markdown code blocks)
                        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                        if json_match:
                            json_str = json_match.group(1)
                        else:
                            # Try to find JSON object directly
                            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                            if json_match:
                                json_str = json_match.group(0)
                            else:
                                json_str = response_text
                        
                        parsed_data = json.loads(json_str)
                        
                        # Validate required fields
                        report_content = parsed_data.get('report_content', '')
                        description = parsed_data.get('description', 'Generated report')
                        scan_type = parsed_data.get('scan_type', 'Unknown')
                        
                        # Don't append signature yet - will append after validation
                        
                        # LINGUISTIC VALIDATION for zai-glm-4.7 (conditionally enabled)
                        import os
                        ENABLE_LINGUISTIC_VALIDATION = os.getenv("ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION", "true").lower() == "true"
                        
                        if ENABLE_LINGUISTIC_VALIDATION:
                            from .enhancement_utils import validate_template_linguistics
                            
                            try:
                                print(f"\n{'='*80}")
                                print(f"🔍 TEMPLATE LINGUISTIC VALIDATION - Starting (fallback path)")
                                print(f"{'='*80}")
                                
                                validated_content = await validate_template_linguistics(
                                    report_content=report_content,
                                    template_config=template_config,
                                    user_inputs=user_inputs,
                                    scan_type=scan_type
                                )
                                
                                report_content = validated_content
                                print(f"✅ TEMPLATE LINGUISTIC VALIDATION COMPLETE")
                                print(f"{'='*80}\n")
                            except Exception as e:
                                print(f"\n{'='*80}")
                                print(f"⚠️ TEMPLATE LINGUISTIC VALIDATION FAILED - continuing with original")
                                print(f"{'='*80}")
                                print(f"[ERROR] {type(e).__name__}: {str(e)[:300]}")
                                print(f"{'='*80}\n")
                        
                        # Append signature AFTER validation (or if validation disabled)
                        if user_signature:
                            from types import SimpleNamespace
                            tmp = SimpleNamespace(report_content=report_content, description=description, scan_type=scan_type)
                            tmp = _append_signature_to_report(tmp, user_signature)
                            report_content = tmp.report_content
                        
                        return {
                            "report_content": report_content,
                            "description": description,
                            "scan_type": scan_type,
                            "model_used": model_name,
                        }
                    except Exception as fallback_error:
                        print(f"[ERROR] Fallback parsing also failed: {fallback_error}")
                        raise ValueError(f"Failed to generate report with {model_name}: {str(e)}. Fallback also failed: {str(fallback_error)}")
                else:
                    # Re-raise if it's not a structured output error
                    raise
        except Exception as primary_error:
            # Try Claude (Anthropic) as fallback when primary fails
            if anthropic_api_key:
                print(f"⚠️ {model_name} failed ({type(primary_error).__name__}) - falling back to {fallback_model}")
                try:
                    report_output = await _generate_report_with_claude_model(
                        fallback_model,
                        f"{fallback_model} (fallback)",
                        user_prompt,
                        system_prompt,
                        anthropic_api_key,
                        user_signature
                    )
                    return {
                        "report_content": report_output.report_content,
                        "description": report_output.description,
                        "scan_type": report_output.scan_type,
                        "model_used": fallback_model,
                    }
                except Exception as fallback_error:
                    print(f"❌ Claude fallback also failed: {type(fallback_error).__name__}")
                    raise ValueError(f"Failed with {model_name} and {fallback_model}. Original: {primary_error}") from primary_error
            else:
                raise

    @staticmethod
    def _parse_skill_sheet_json(raw: str, keys: List[str]) -> Dict:
        """
        Extract a JSON object from a GLM string response.
        Handles markdown code fences and stray leading/trailing text.
        """
        import json, re

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        candidate = fence_match.group(1).strip() if fence_match else raw.strip()

        # Try direct parse first
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            # Find the outermost { ... } block
            brace_match = re.search(r'\{[\s\S]*\}', candidate)
            if not brace_match:
                raise ValueError(f"No JSON object found in model response. Raw: {raw[:300]}")
            parsed = json.loads(brace_match.group())

        # Validate expected keys are present
        missing = [k for k in keys if k not in parsed]
        if missing:
            raise ValueError(f"Model response missing keys {missing}. Got: {list(parsed.keys())}")
        return parsed

    async def analyze_reports_and_generate_config(
        self,
        scan_type: str,
        contrast: str,
        protocol_details: str,
        reports: List[Dict[str, str]],
        api_key: str,
    ) -> Dict:
        """
        Stub for legacy /api/templates/analyze-reports endpoint.
        Returns a minimal template_config inferred from scan_type and contrast.
        Will be replaced by skill-sheet flow in Iteration 2.
        """
        return {
            "template_config": {
                "scan_type": scan_type,
                "contrast": contrast,
                "protocol_details": protocol_details,
                "content_style": "structured_prose",
                "report_style": "structured",
            },
            "detected_profile": "inferred",
        }

    async def analyze_examples_to_skill_sheet(
        self,
        examples: List[Dict[str, str]],
        scan_type: str,
        api_key: str,
    ) -> Dict:
        """
        Analyse example reports and generate an initial skill sheet.

        Args:
            examples: List of dicts with 'label' (optional) and 'content' keys
            scan_type: Scan type string (e.g. "CT chest with contrast")
            api_key: Cerebras API key

        Returns:
            { skill_sheet: str, summary: str, questions: list[str] }
        """
        from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model, _log_glm_reasoning

        model_name = MODEL_CONFIG["SKILL_SHEET_ANALYZER"]

        examples_text = ""
        for i, ex in enumerate(examples, 1):
            label = ex.get("label") or f"Example {i}"
            content = ex.get("content", "").strip()
            examples_text += f"\n\n### {label}\n```\n{content}\n```"

        system_prompt = """You are an expert radiology reporting analyst. Your task is to reverse-engineer a radiologist's reporting style from their example reports and produce a Skill Sheet — a construction manual that allows an AI to write reports indistinguishable from this radiologist's own work.

A Skill Sheet has two layers:
1. STRUCTURE — the skeleton: sections, ordering, mandatory fields, fixed blocks. This is the blueprint — precise and checklist-verifiable.
2. CONSTRUCTION VOICE — how this radiologist thinks and writes within that structure. Quoted patterns, prose rhythm, decision logic, impression reasoning. This is their cognitive fingerprint.

Both layers must be grounded in the examples. Quote actual text to demonstrate every convention. Do not invent rules not evidenced in the reports.

IMPORTANT: A Global Style Guide already covers universal rules (British English, impersonal voice, terminology consistency, section boundaries, consolidation, measurement conventions). Do NOT re-extract these. Focus ONLY on what is specific to this radiologist and this scan type.

The Skill Sheet must follow this structure:

# Skill Sheet: {descriptive name}

## Scan Context
- Modality and scan type
- Clinical setting (e.g. oncology follow-up, acute presentation, surveillance)

## Structural Pattern
- Sections included, in order
- For each section: always present / conditionally present (state the condition) / never omitted

## Fixed Blocks
Verbatim text that must be reproduced exactly and never paraphrased. Extract the precise wording from the examples. Use {laterality}, {contrast_type}, or {field_strength} for patient-specific values that vary between cases.
- TECHNIQUE: [exact wording with parameters]
- Any other sections with fixed standardised phrasing: [exact wording]

When extracting fixed blocks, tag any statement that describes the patient's state or imaging history as [NEEDS VERIFICATION]. A statement is factual if it could be false for a different patient — "No previous CMR available", "The study is of diagnostic quality", "No pericardial effusion" are all patient-state assertions. A statement is structural if it describes what was performed and how — "MRI of the {laterality} shoulder performed at 1.5 Tesla", "Sequences include coronal and sagittal proton density fat-saturated" are structural. When in doubt, tag it. The cost of an unnecessary verification is trivial; the cost of a missed factual error in a signed report is not.

## Per-Section Construction Rules
For each FINDINGS section/paragraph, specify:

### [SECTION/PARAGRAPH NAME]
- **header**: Does this paragraph have a visible heading in the example reports? A heading exists if and only if it appears on its own line, separated from the paragraph content below it, in the examples. If yes: `header: "[exact text as it appears]"` (e.g. `header: "Lung Parenchyma:"`). If no visible heading — just a paragraph break: `header: none`. Text that appears only as your organisational label during extraction is NOT a header.
- **Mandatory fields**: fields that must always be present regardless of findings
- **Field ordering**: sequence fields must follow within the section
- **Mandatory negatives**: exact phrasing quoted from the examples (e.g. "No pericardial effusion is identified")
- **Multi-clause fields**: fields requiring more than one sentence (e.g. BONES AND SOFT TISSUES = osseous sentence + soft tissues sentence)
- **Conditional fields**: fields present only when a trigger is met (state the trigger explicitly)
- **Normal pattern**: quote a representative sentence showing how this radiologist describes this section when normal. Example: "The supraspinatus tendon is intact with no partial or full thickness tear."
- **Abnormal pattern**: quote a representative sentence showing how this radiologist describes pathology in this section. Example: "Full thickness tear of the supraspinatus tendon at the anterior footprint measuring 16mm x 11mm, retracting to the level of the glenohumeral joint."
- **Paragraph opening convention**: how does this radiologist open this paragraph? Direct noun phrase? Index abnormality first? Structure-by-structure sweep?

## Terminology Rules
- **Preferred terms**: [term] — use always (e.g. "thrombus")
- **Suppressed terms**: [term] — never use, even if synonymous (e.g. "filling defect")
- **Paired rules**: where a preferred term has a corresponding suppressed term, list both together

## Interpretive Clause Rules
Specific findings that require a mandatory interpretive or causal attribution clause.
Format: IF [finding] THEN append [exact required clause]
Quote the exact clause from the examples.

## Conditional Suppression Rules

SECOND-ORDER PASS: After extracting mandatory negatives, interpretive clauses, and fixed phrase patterns above, reason through each one with the following questions. Limit to finding states that are common clinical presentations for this scan type — not every theoretically possible scenario.

For each mandatory negative:
- What finding state does this negative assume? (e.g. "no subluxation or tear" assumes the tendon is in situ)
- Is there a finding state — documented in the examples or common for this scan type — where this negative would be contradictory or clinically inappropriate?
- IF yes: document as IF [alternative state] THEN suppress [phrase] AND replace with [alternative phrase or nothing]
- IF the alternative state is clinically conceivable but not in the examples: flag as [NEEDS CLARIFICATION] with the specific scenario

For each fixed phrase pattern and interpretive clause:
- Does this phrase assume a particular finding state? If the finding state differs, does the phrase still hold?
- Are there severity thresholds where the language becomes inappropriate? (e.g. "low volume bursitis" valid for mild fluid but inappropriate when bursa is distended or collapsed)

For each grading or scoring rule:
- Does the clinical weight of the grade change depending on adjacent findings? (e.g. Goutallier grade 0 teres minor is a positive prognostic indicator in a massive cuff tear but merely a completeness check in a normal shoulder)
- If yes, document the contextual interpretation rule

## Measurement and Grading Rules
- How measurements appear in prose: quote an example sentence showing integration (e.g. "measuring 16mm x 11mm" vs "a 16mm tear")
- Grading systems used: [system name], when triggered, how referenced
- Threshold values with explicit numeric cutoffs and the exact language for each tier
- Borderline ranges and their required language

## Reference Values
Extract ONLY explicitly stated reference values and thresholds from the example reports — values the radiologist wrote as declared normal ranges, cutoffs, or reference standards. Examples:
- "Left atrium: 28 cm² (normal value <24 cm²)" → extract: LA normal <24 cm²
- "Pre-contrast T1: 1020 ms (normal: 891-1035 ms at 1.5T)" → extract: T1 1.5T normal 891-1035 ms

Do NOT infer thresholds from qualifier-value pairings. If a report describes LVEF 69% as "normal", that is one data point — it does not define where normal ends. Do not add "LVEF 69% = normal" to this table.

For parameters where the examples use qualifiers (normal, reduced, increased) but do not state explicit thresholds, flag as [NEEDS CLARIFICATION] — these should be raised in the Q&A phase so the radiologist can provide their thresholds, which then become explicit entries in this table.

This table is the sole authority for reference values at generation time. Values not in this table must not be fabricated.

## Impression Construction Rules

This section defines how this radiologist builds their impression — not just what it contains, but the reasoning and construction method they use. Analyse every impression across all examples to extract these patterns.

### Quoted examples
For each example report, quote the FULL impression verbatim. These are the ground truth for every rule below.

### Sentence construction pattern
How does this radiologist build an impression sentence? Describe the mechanical pattern:
- What comes first in a sentence? (diagnosis, location, measurement, context)
- How are related findings chained? (semicolons, commas, "with associated...")
- Where do recommendations appear? (semicolon clause at end, separate sentence, final standalone sentence)
- Quote a representative impression sentence and annotate its structure.

### Inclusion logic
Compare what appeared in FINDINGS vs what was promoted to IMPRESSION across all examples.
- Which findings made the impression?
- Which findings stayed in FINDINGS only?
- What is the threshold — what makes a finding "impression-worthy" for this radiologist?

### Sentence grouping
- How many impression sentences does this radiologist typically write? (count across examples)
- What determines whether findings get merged into one sentence vs separated?
- Do findings sharing a management pathway get merged?

### Recommendation phrasing
- Quote every recommendation phrase from the examples verbatim
- How are recommendations integrated — as a semicolon clause closing the finding sentence, as a separate sentence, or as a final summary sentence?
- Is there a graduation pattern? (e.g. "physiotherapy review" → "orthopaedic review" → "orthopaedic review for surgical planning")

### Normal study impression
- If a normal example is included, quote the exact impression sentence
- What is the pattern for a normal/negative impression? (single sentence answering clinical question, or list of excluded differentials?)

### Restatement rules
- Which measurements from the body are restated in the impression? (all? key only? none?)
- Are grading scores restated? Which ones?
- Is any new context added in the impression that wasn't in findings (e.g. risk stratification, clinical correlation)?

## Negative Finding Rules
- Per-section mandatory negatives: list explicitly by section with exact quoted phrasing
- Normal finding behaviour when section is entirely normal: quote the exact sentence used

## Incidental Findings Rules
- Where are incidental findings placed? (dedicated section or within anatomical paragraph)
- Quote how an incidental finding was described in the examples, if present
- What was the inclusion threshold — did any finding get excluded as too minor?
- How are incidentals referenced in the impression, if at all?

## Domain Rules
Specific always/never statements and domain conventions not covered above, extracted directly from the examples. Quote actual phrases to illustrate each rule.

---

Where a rule cannot be determined from the examples alone, flag it explicitly as [NEEDS CLARIFICATION] so it can be raised as a question."""

        user_prompt = f"""Analyse these example radiology reports for scan type: **{scan_type}**
{examples_text}

Return a JSON object with exactly these three keys:
- "skill_sheet": the complete Skill Sheet markdown document following the structure above
- "summary": a structured object (NOT a string) for visual rendering in the UI. Must follow this exact JSON shape:

{{
  "structure": {{
    "sections": [
      {{ "name": "FINDINGS", "paragraphs": ["short description of paragraph 1", "short description of paragraph 2", "..."] }},
      {{ "name": "IMPRESSION", "paragraphs": [] }}
    ]
  }},
  "voice": {{
    "description": "one short sentence (under 12 words) describing the writing voice",
    "phrases": ["quoted signature phrase 1", "quoted signature phrase 2", "quoted signature phrase 3"]
  }},
  "conventions": {{
    "rules": [
      {{ "title": "Short rule title (3-6 words)", "detail": "One sentence explanation, may include a quoted example." }},
      {{ "title": "...", "detail": "..." }}
    ]
  }},
  "impression": {{
    "flow": ["Step 1 noun", "Step 2 noun", "Step 3 noun"],
    "detail": "One short sentence describing how the impression is constructed."
  }}
}}

Rules for the structured summary:
- structure.sections: list every top-level section in the order they appear. Paragraphs is the list of internal paragraph descriptions within each section (empty list if the section has no internal paragraph divisions). Each paragraph description is a short noun phrase (under 10 words).
- voice.description: one terse sentence. No "This template" or "This radiologist" framing — just adjectives and tone descriptors.
- voice.phrases: 3-5 verbatim quoted phrases from the example reports that capture the signature voice.
- conventions.rules: 4-6 of the most distinctive scan-specific rules. Title is a short label, detail is one sentence.
- impression.flow: 2-4 nouns describing the construction sequence (e.g. ["Pattern", "Aetiology", "Recommendation"]).
- impression.detail: one short sentence about sentence count, grouping, recommendation integration.

Keep everything terse and scannable. This is rendered as visual hierarchy, not paragraphs of prose.

- "questions": an array of exactly 3 objects, each with "question" (the clarifying question) and "suggestions" (array of 2-3 short clickable answer options the radiologist can pick from). Target the most impactful rules flagged as [NEEDS CLARIFICATION] or where examples were ambiguous. Suggestions should be concrete, specific answers — not generic. Do not ask about things clearly evidenced in the reports"""

        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=str,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=True,
            model_settings={
                "temperature": 0.8,
                "top_p": 0.95,
                "max_tokens": 40960,
                "extra_body": {
                    "disable_reasoning": False,
                    "clear_thinking": False,
                },
            },
        )

        _log_glm_reasoning(result, f"{model_name} (Skill Sheet Analyze) - GLM Reasoning")
        raw = result.output if hasattr(result, "output") else str(result)
        parsed = self._parse_skill_sheet_json(raw, ["skill_sheet", "summary", "questions"])
        return {
            "skill_sheet": parsed["skill_sheet"],
            "summary": parsed["summary"],
            "questions": parsed["questions"],
        }

    async def generate_test_case(
        self,
        examples: List[Dict[str, str]],
        scan_type: str,
        api_key: str,
    ) -> Dict:
        """
        Generate a novel test case (clinical history + scratchpad findings)
        from example reports. Runs in parallel with skill sheet analysis.
        """
        from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model, _log_glm_reasoning

        model_name = MODEL_CONFIG["SKILL_SHEET_ANALYZER"]

        examples_text = ""
        for i, ex in enumerate(examples, 1):
            label = ex.get("label") or f"Example {i}"
            content = ex.get("content", "").strip()
            examples_text += f"\n\n### {label}\n```\n{content}\n```"

        system_prompt = """You are generating a test case for a radiology report template. You will be given example reports of a specific scan type. Your job is to invent a novel clinical scenario and raw findings for the same scan type that a radiologist can use to test their template.

The test case has two parts:
1. A terse clinical history in referral format
2. Raw scratchpad findings as a radiologist would dictate before any report is written"""

        user_prompt = f"""These are example reports for scan type: **{scan_type}**
{examples_text}

Generate a JSON object with exactly two keys:

- "sample_clinical_history": terse referral format — age, sex abbreviated, key clinical facts as noun phrases, query statement last. Must be clinically coherent with the findings below. Do not copy from the examples.

- "sample_findings": a novel clinical scenario that is distinct from all the examples above — different primary diagnosis, different pathology combination, different severity level. Every finding must be internally consistent — if one finding implies a pathological state, no other finding should contradict it. Write as raw scratchpad: terse bullet points, abbreviations, values with units. This is pre-report notation — what a radiologist would scribble before the report is constructed, not prose, not formatted sentences. Include only raw observations. Do not include reference ranges or normal value thresholds — those are applied at report generation time, not dictation time. Include at least one incidental finding. Do not composite or rehash the example findings."""

        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=str,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=True,
            model_settings={
                "temperature": 0.9,
                "top_p": 0.95,
                "max_tokens": 4096,
                "extra_body": {
                    "disable_reasoning": False,
                    "clear_thinking": False,
                },
            },
        )

        _log_glm_reasoning(result, f"{model_name} (Test Case Generator) - GLM Reasoning")
        raw = result.output if hasattr(result, "output") else str(result)
        parsed = self._parse_skill_sheet_json(raw, ["sample_clinical_history", "sample_findings"])
        return {
            "sample_clinical_history": parsed["sample_clinical_history"],
            "sample_findings": parsed["sample_findings"],
        }

    async def refine_skill_sheet(
        self,
        skill_sheet: str,
        message: str,
        chat_history: List[Dict[str, str]],
        api_key: str,
    ) -> Dict:
        """
        Refine a skill sheet based on radiologist feedback via chat.

        Args:
            skill_sheet: Current skill sheet markdown
            message: Radiologist's latest message
            chat_history: Previous turns as [{"role": "user"|"assistant", "content": str}]
            api_key: Cerebras API key

        Returns:
            { skill_sheet: str, response: str }
        """
        from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model, _log_glm_reasoning

        model_name = MODEL_CONFIG["SKILL_SHEET_REFINER"]

        history_text = ""
        for turn in chat_history:
            role_label = "Radiologist" if turn["role"] == "user" else "Assistant"
            history_text += f"\n\n**{role_label}:** {turn['content']}"

        system_prompt = """You are an expert radiology reporting analyst helping a radiologist refine a Skill Sheet for their report template.

A Skill Sheet is a markdown document that acts as a construction guide for an AI system generating reports. Your job is to:
1. Understand the radiologist's feedback or instruction
2. Update the Skill Sheet precisely to reflect it
3. Respond conversationally confirming what you changed and why

Rules:
- Only update sections that the radiologist's message clearly affects
- Keep all existing content that is not contradicted
- If the message is a question rather than an instruction, answer it and ask if they want the skill sheet updated
- Be concise in your response (2-4 sentences)
- The skill_sheet field must be the complete document, not a diff"""

        history_section = f"\n\n=== CONVERSATION HISTORY ==={history_text}" if history_text.strip() else ""

        user_prompt = f"""Current Skill Sheet:
```markdown
{skill_sheet}
```
{history_section}

=== RADIOLOGIST'S MESSAGE ===
{message}

Return a JSON object with:
- "skill_sheet": the updated complete Skill Sheet markdown (unchanged if no update needed)
- "response": your conversational reply to the radiologist (2-4 sentences)"""

        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=str,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=True,
            model_settings={
                "temperature": 0.8,
                "top_p": 0.95,
                "max_tokens": 40960,
                "extra_body": {
                    "disable_reasoning": False,
                    "clear_thinking": False,
                },
            },
        )

        _log_glm_reasoning(result, f"{model_name} (Skill Sheet Refine) - GLM Reasoning")
        raw = result.output if hasattr(result, "output") else str(result)
        parsed = self._parse_skill_sheet_json(raw, ["skill_sheet", "response"])
        return {
            "skill_sheet": parsed["skill_sheet"],
            "response": parsed["response"],
        }

    async def test_generate_with_skill_sheet(
        self,
        skill_sheet: str,
        scan_type: str,
        clinical_history: str,
        findings_input: str,
        api_key: str,
    ) -> Dict:
        """
        Generate a test report using a skill sheet (no saved template required).

        Args:
            skill_sheet: Skill sheet markdown
            scan_type: Scan type string
            clinical_history: Clinical history text
            findings_input: Raw findings/dictation from radiologist
            api_key: Cerebras API key

        Returns:
            { report_content: str, model_used: str }
        """
        from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model, _log_glm_reasoning
        from .global_style_guide import (
            SYSTEM_PREAMBLE, GLOBAL_STYLE_GUIDE,
            PRE_WRITING_ANALYSIS, VERIFICATION_CHECKLIST,
        )

        model_name = MODEL_CONFIG["SKILL_SHEET_TEST_GENERATE"]

        system_prompt = f"""{SYSTEM_PREAMBLE}

{GLOBAL_STYLE_GUIDE}

## TEMPLATE SKILL SHEET

The following skill sheet defines scan-specific reporting conventions for this template.
It inherits all rules from the Global Style Guide above. Where a skill sheet rule
conflicts with a global rule, the skill sheet takes precedence.

{skill_sheet}"""

        user_prompt = f"""## INPUTS

Scan Type: {scan_type}
Clinical History: {clinical_history}
Findings: {findings_input}

{PRE_WRITING_ANALYSIS}

{VERIFICATION_CHECKLIST}"""

        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=str,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=True,
            model_settings={
                "temperature": 0.8,
                "top_p": 0.95,
                "max_tokens": 40960,
                "extra_body": {
                    "disable_reasoning": False,
                    "clear_thinking": False,
                },
            },
        )

        _log_glm_reasoning(result, f"{model_name} (Skill Sheet Test Generate) - GLM Reasoning")
        report_content = result.output if hasattr(result, "output") else str(result)
        return {
            "report_content": report_content,
            "model_used": model_name,
        }
