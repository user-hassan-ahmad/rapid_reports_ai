"""Template Manager for Custom Templates
Handles custom template operations similar to PromptManager but for user-created templates
"""
import re
from typing import Dict, List, Optional, Any


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
        Normalize advanced config - simplified architecture with NO backward compatibility.
        No active users, so clean slate.
        
        Args:
            advanced: Current advanced config (may be incomplete)
            section_type: 'findings' or 'impression'
        
        Returns:
            Complete advanced config with defaults filled in
        """
        if section_type == 'findings':
            defaults = {
                'instructions': '',
                'writing_style': 'standard',
                'organization': 'clinical_priority',
                'format': 'prose',
                'use_subsection_headers': False
            }
        else:  # impression
            defaults = {
                'instructions': '',
                'verbosity_style': 'standard',
                'format': 'prose',
                'differential_approach': 'if_needed',
                'recommendations': {
                    'specialist_referral': True,
                    'further_workup': True,
                    'imaging_followup': False,
                    'clinical_correlation': False
                }
            }
        
        # Merge: existing values override defaults
        return {**defaults, **advanced}
    
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
            system_prompt = """You are a senior consultant radiologist creating a FINDINGS section template.

Generate a STRUCTURED FILL-IN TEMPLATE with precise placeholder syntax.

PLACEHOLDER TYPES (use EXACTLY as specified):

1. VARIABLES: {VAR_NAME}
   - For named measurements that need explicit matching
   - Example: "LVEF={LVEF}%" 
   - Limit to 5-7 critical measurements only (creates labeled input fields)

2. MEASUREMENTS: xxx
   - Generic measurement blanks (always lowercase)
   - Example: "measuring xxx mm in diameter"
   - Use when specific variable name not needed

3. ALTERNATIVES: [option1/option2]
   - CRITICAL RULE: Brackets wrap ONLY the alternative words/phrases, NEVER entire sentences
   - Keep alternatives SIMPLE: single words or short phrases (2-3 words max per option)
   - Use alternatives SPARINGLY - only when there are 2-3 clear, mutually exclusive options
   - AI selects ONE option based on findings and removes brackets
   - Limit to 2-3 options max per bracket
   - Each option must be grammatically compatible with the surrounding sentence
   
   CORRECT EXAMPLES:
   ✓ "Size is [normal/increased]" → "Size is normal" or "Size is increased"
   ✓ "Effusion is [present/absent]" → "Effusion is present" or "Effusion is absent"
   ✓ "Enhancement is [homogeneous/heterogeneous]" → works grammatically
   ✓ "Wall motion is [normal/abnormal]" → simple, clear alternatives
   
   WRONG EXAMPLES (DO NOT DO THIS):
   ✗ "[Effusion is present/absent]" → brackets wrap full sentence
   ✗ "[No effusion/Effusion present]" → different sentence structures, won't read well
   ✗ "The [lungs are clear/lungs show consolidation]" → brackets wrap too much
   ✗ "There is [a mass measuring 4cm/no mass]" → entire phrases wrapped
   ✗ "Size is [normal/increased/decreased/slightly enlarged]" → too many options
   ✗ "Enhancement pattern shows [homogeneous enhancement with smooth margins/heterogeneous enhancement with irregular borders]" → options too complex

4. INSTRUCTIONS: // instruction
   - ACTIONABLE guidance for AI behavior (stripped from final output)
   - Must tell AI WHAT TO DO or HOW TO HANDLE a section
   - Use SPARINGLY (2-4 per template) at key decision points only
   - GOOD examples (actionable):
     • "// Describe only if abnormal"
     • "// Skip this section if not assessed"
     • "// Grade severity based on measurements"
   - BAD examples (just comments/labels - DON'T USE):
     • "// Systematic review of structures" (not actionable)
     • "// Perfusion assessment" (just a label)
     • "// Additional findings" (just a label)

STRUCTURE RULES:
- Keep structure SIMPLE and FLEXIBLE
- Use clear section headers (e.g., "LEFT VENTRICLE", "RIGHT VENTRICLE")
- Pre-write complete prose with placeholders embedded naturally
- Static text preserved exactly during report generation
- British English is automatic (don't add // comments about it)
- Don't over-complicate - use alternatives only where they genuinely help

EXAMPLE TEMPLATE (simple and clear):

LEFT VENTRICLE
End-diastolic volume is [normal/increased] at xxx ml/m².
Systolic function is [preserved/reduced] with LVEF={LVEF}%.

// Describe wall motion only if abnormal
WALL MOTION
Regional abnormalities are [present/absent].

PERFUSION ASSESSMENT
First-pass perfusion shows [normal/reduced] enhancement.
Defects are [present/absent] in the xxx territory.

RIGHT VENTRICLE
RV size is [normal/dilated] at xxx ml/m².

Do NOT include the "FINDINGS:" header - just the template content."""
        
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
        model_name = "zai-glm-4.6"  # Cerebras Zai-GLM for template generation
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
        model_name = "zai-glm-4.6"  # Cerebras Zai-GLM for instruction suggestions
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
    
    def _build_detailed_style_guidance(self, advanced: dict, section_type: str = 'findings') -> str:
        """Ultra-clean style guidance with zero redundancy"""
        guidance_parts = []
        
        # === WRITING STYLE (Primary - handles everything) ===
        writing_style = advanced.get('writing_style', 'standard')
        
        style_guidance = {
            'concise': """
=== WRITING STYLE: CONCISE ===

COMMUNICATION GOAL:
Rapid information transfer for experienced readers. Consultant-to-consultant style.

CORE PRINCIPLE:
Strip to essentials. If removing a word doesn't change clinical understanding, remove it.

DECISION FRAMEWORK:
For each word, ask: "Does this change clinical understanding?"
- Size + critical morphology: YES → Include
  ✓ "4cm spiculated mass in right upper lobe"
- Decorative descriptors: NO → Remove
  ✗ "well-defined", "irregular", "appears to be"
- Passive constructions: NO → Eliminate
  ✗ "are present", "is identified" → ✓ "present"
- Anatomical subsegments: NO → Use general location
  ✓ "right upper lobe" not "lateral segment of right upper lobe"

Key rule: Spell out anatomical terms (no RUL, PA, LLL acronyms).

EXAMPLE OUTPUT:
"Large filling defects in the right pulmonary artery extending to segmental branches. Additional defect in the left lower lobe. Right ventricle dilated, RV/LV ratio 1.3. Mild IVC reflux. Small right effusion."
""",
            
            'standard': """
=== WRITING STYLE: STANDARD ===

COMMUNICATION GOAL:
Balanced professional NHS reporting for multidisciplinary teams and clinical documentation.

CORE PRINCIPLE:
Include what's clinically relevant with appropriate detail. Balance completeness with readability.

DECISION FRAMEWORK:
Ask: "Does this detail add clinical value or just length?"
- Core findings: Full description with key morphology
- Secondary findings: Appropriate detail
- Normal structures: Group efficiently
- Use natural sentence flow (passive voice OK when it reads better)

EXAMPLE OUTPUT:
"Large filling defects are present in the right main pulmonary artery, extending into segmental branches. An additional filling defect is identified in the left lower lobe. The right ventricle is moderately dilated with an RV/LV ratio of 1.3. Mild IVC reflux suggests right heart strain. A small right pleural effusion is present."
""",
            
            'detailed': """
=== WRITING STYLE: DETAILED ===

COMMUNICATION GOAL:
Comprehensive documentation for complex cases, academic review, or medico-legal contexts.

CORE PRINCIPLE:
Document the complete picture with full characterization and precision. Favor thoroughness over brevity.

DECISION FRAMEWORK:
Ask: "What's the most complete way to describe this finding?"
- Include full morphological characterization
- Precise subsegmental anatomical locations
- Three-dimensional measurements when available
- Rich descriptive language ("well-defined", "heterogeneous", etc.)
- All associated findings and normal structures

EXAMPLE OUTPUT:
"Multiple large filling defects are identified within the right main pulmonary artery, extending distally into the segmental branches of the right upper and lower lobes. An additional filling defect is present in the posterior basal segmental artery of the left lower lobe. The right ventricle demonstrates moderate dilatation with an RV/LV ratio of 1.3. Associated mild reflux of contrast material into the IVC and hepatic veins is observed. Wedge-shaped consolidation is evident in the posterior segment of the right lower lobe, consistent with pulmonary infarction. A small right-sided pleural effusion is noted."
"""
        }
        guidance_parts.append(style_guidance.get(writing_style, style_guidance['standard']))
        
        # === ORGANIZATION ===
        organization = advanced.get('organization', 'clinical_priority')
        org_guidance = {
            'clinical_priority': """
=== FINDING SEQUENCE: Clinical Priority ===

Lead with critical findings, then resume template structure.
1. Start with acute/significant abnormalities
2. Complete regional context
3. Resume template flow
4. Each finding mentioned ONCE only
""",
            'template_order': """
=== FINDING SEQUENCE: Template Order ===

Follow template's anatomical structure exactly.
Do not reorder based on clinical significance.
"""
        }
        guidance_parts.append(org_guidance.get(organization, org_guidance['clinical_priority']))
        
        # === FORMAT ===
        format_style = advanced.get('format', 'prose')
        format_guidance = {
            'prose': "FORMAT: Flowing prose paragraphs with natural breaks",
            'bullets': "FORMAT: Bullet points (•) - one finding per bullet"
        }
        guidance_parts.append(format_guidance.get(format_style, format_guidance['prose']))
        
        # === SUBSECTION HEADERS ===
        if advanced.get('use_subsection_headers', False):
            guidance_parts.append("""
SUBSECTION HEADERS: ENABLED
Use CAPS headers with colons (e.g., "CHEST:", "ABDOMEN:")
Works with both prose and bullets.
""")
        
        # === CUSTOM INSTRUCTIONS ===
        if advanced.get('instructions', '').strip():
            guidance_parts.append(f"CUSTOM INSTRUCTIONS:\n{advanced['instructions']}")
        
        # === NHS CORE RULES ===
        guidance_parts.append("""
NHS STYLE RULES:
- British English: oesophagus, haemorrhage, oedema, paediatric
- Measurements: Space between number and unit ("5 cm")
- Avoid: "There is/are", "demonstrates", "shows", "is seen"
- Prefer: Direct statements, active verbs
""")
        
        return "\n\n".join(guidance_parts)
    
    def _build_impression_style_guidance(self, advanced: dict) -> str:
        """Generate IMPRESSION-specific style guidance"""
        guidance_parts = []
        
        # === VERBOSITY STYLE (handles measurements, comparisons, incidentals) ===
        verbosity_style = advanced.get('verbosity_style', 'standard')
        
        verbosity_map = {
            'brief': """
=== IMPRESSION VERBOSITY: BRIEF ===

COMMUNICATION GOAL:
Corridor conversation style. What you'd tell a colleague walking past - diagnosis only.

CORE PRINCIPLE:
Distill to the essential diagnosis and critical complications. Strip everything else.

DECISION FRAMEWORK:
Ask: "Would I say this in a 5-second corridor conversation?"
- If YES → Include
  ✓ "Bilateral pulmonary emboli with right heart strain"
  ✓ "New pulmonary emboli" (comparison when relevant)
  ✓ "Progression of disease"
- If NO → Omit
  ✗ Secondary findings, measurements, incidentals

SENTENCE CONSTRUCTION:
Single concise statement - diagnosis with critical qualifiers:
✓ "Bilateral pulmonary emboli with right heart strain."
✓ "New left lower lobe consolidation."
✓ "Progression of metastatic disease."

EXAMPLE OUTPUT:
"Bilateral pulmonary emboli with right heart strain."
""",
            
            'standard': """
=== IMPRESSION VERBOSITY: STANDARD ===

COMMUNICATION GOAL:
Balanced professional summary for MDT/documentation. Complete clinical picture with appropriate detail.

CORE PRINCIPLE:
Include what's clinically relevant for management decisions. Balance completeness with conciseness.

DECISION FRAMEWORK:
Ask: "Does this finding matter for clinical management or understanding the case?"
- If YES → Include with appropriate detail
  ✓ Primary diagnosis with severity
  ✓ Key secondary findings related to primary process
  ✓ Measurements when they inform management
  ✓ Comparisons when relevant (simple measured changes)
  ✓ Actionable incidentals only (require follow-up/referral)
- If NO → Omit
  ✗ Non-actionable incidentals
  ✗ Excessive measurement precision

SENTENCE CONSTRUCTION:
2-3 clear sentences covering the clinical picture:
✓ "Bilateral pulmonary emboli are present with right heart strain. A small right pleural effusion and right lower lobe infarction are noted."

EXAMPLE OUTPUT:
"Bilateral pulmonary emboli are present with right heart strain. A small right pleural effusion and right lower lobe infarction are noted."
""",
            
            'detailed': """
=== IMPRESSION VERBOSITY: DETAILED ===

COMMUNICATION GOAL:
Comprehensive documentation for complex cases, academic review, or medico-legal records.

CORE PRINCIPLE:
Document the complete clinical picture with full characterization and precision. Favor thoroughness.

DECISION FRAMEWORK:
Ask: "Is this finding present on the study?"
- If YES → Document with full detail
  ✓ Primary diagnosis with complete characterization
  ✓ All secondary and associated findings
  ✓ Precise measurements (three dimensions when available)
  ✓ Dated comparisons when relevant
  ✓ Actionable incidentals (require follow-up/referral)

SENTENCE CONSTRUCTION:
Multiple comprehensive sentences covering all findings systematically:
✓ "Bilateral pulmonary emboli are present with RV dilatation (RV/LV 1.3) and contrast reflux. Additional findings include a small right pleural effusion and wedge-shaped consolidation in the RLL consistent with infarction."

EXAMPLE OUTPUT:
"Bilateral pulmonary emboli are present with RV dilatation (RV/LV 1.3) and contrast reflux. Additional findings include a small right pleural effusion and wedge-shaped consolidation in the RLL consistent with infarction."
"""
        }
        guidance_parts.append(verbosity_map.get(verbosity_style, verbosity_map['standard']))
        
        # === FORMAT ===
        # Handle backward compatibility: map impression_format to format
        impression_format = advanced.get('format') or advanced.get('impression_format', 'prose')
        format_map = {
            'prose': "FORMAT: Prose (traditional narrative)",
            'bullets': "FORMAT: Bullets (• symbol)",
            'numbered': "FORMAT: Numbered list (1., 2., etc.)"
        }
        guidance_parts.append(format_map.get(impression_format, format_map['prose']))
        
        # === DIFFERENTIAL ===
        differential = advanced.get('differential_approach', 'if_needed')
        # Handle backward compatibility: map old differential_style to differential_approach
        if 'differential_style' in advanced and 'differential_approach' not in advanced:
            old_diff = advanced.get('differential_style')
            if old_diff in ['always_brief', 'always_detailed']:
                differential = 'always'
            elif old_diff == 'none':
                differential = 'none'
            else:
                differential = 'if_needed'
        
        differential_map = {
            'none': "DIFFERENTIAL: Do NOT include",
            'if_needed': "DIFFERENTIAL: Only when diagnosis uncertain (2-3 alternatives)",
            'always': "DIFFERENTIAL: ALWAYS include (2-3 alternatives, ordered by likelihood)"
        }
        guidance_parts.append(differential_map.get(differential, differential_map['if_needed']))
        
        # === RECOMMENDATIONS ===
        recommendations = self._build_impression_recommendations_guidance(
            advanced.get('recommendations', {})
        )
        if recommendations:
            guidance_parts.append(recommendations)
        
        # === CUSTOM INSTRUCTIONS ===
        if advanced.get('instructions', '').strip():
            guidance_parts.append(f"CUSTOM INSTRUCTIONS:\n{advanced['instructions']}")
        
        return "\n\n".join(guidance_parts)
    
    def _build_impression_recommendations_guidance(self, recommendations_config: dict) -> str:
        """Generate recommendation guidance from multi-checkbox config"""
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

{self._build_detailed_style_guidance(advanced, section_type='findings')}
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

{self._build_detailed_style_guidance(advanced, section_type='findings')}
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

{self._build_detailed_style_guidance(advanced, section_type='findings')}
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

{self._build_detailed_style_guidance(advanced, section_type='findings')}
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

2. xxx measurements:
   - Replace with measurements from findings
   - If measurement not provided → LEAVE AS xxx (do not estimate)

3. [option1/option2] alternatives:
   - SELECT the most appropriate option based on findings
   - Remove brackets, keep selected option only
   - Example: "[normal/increased]" → "normal" or "increased"

4. // instructions:
   - Follow guidance during generation WHEN filling content
   - STRIP all // lines from final output (do not include in report)
   - IMPORTANT: // instructions guide HOW to describe WHEN input exists, NOT whether to include the section header

5. BLANK SECTIONS (no corresponding input):
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
            _get_model_provider,
            _get_api_key_for_provider,
            _run_agent_with_model,
            _append_signature_to_report,
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
                
                # Build comprehensive impression guidance
                style_guidance = self._build_impression_style_guidance(advanced)
                recommendations_guidance = self._build_impression_recommendations_guidance(recommendations_config)
                
                impression_prompt = f"""
### {display_name} SECTION - Synthesize from Findings

**Task**: Generate impression synthesizing key findings

=== CRITICAL GENERAL RULES ===

**1. COMMIT TO DIAGNOSIS WHERE POSSIBLE**:
- When imaging findings are definitive and support a clear conclusion, state the diagnosis directly using definitive language
- Use definitive statements (e.g., "X is present", "Y demonstrates Z", "Diagnosis: [condition]") rather than hedging when evidence is clear
- Reserve uncertainty language ("consistent with", "suspicious for", "cannot exclude") only when findings are truly non-specific or require further workup.
- If differential_approach is set to "if_needed" and diagnosis is clear, state it definitively rather than listing alternatives

**2. NO SEPARATE SECTIONS**:
- The impression section must contain ALL diagnostic conclusions, recommendations, and follow-up guidance within a single unified section
- DO NOT create separate sections such as "Recommendations", "Plan", "Follow-up", "Management", "Next Steps", or any other section headers
- All recommendations, follow-up suggestions, and management guidance must be integrated into the impression text itself
- If recommendations are configured, include them within the impression prose/bullets, not as a separate section

**Clinical Question** (from history):
{clinical_history}

**PRIORITY PHILOSOPHY**: This is a "Flexible" synthesis section. Follow the template's language/headers if provided, but PRIORITIZE findings according to the style settings below. Clinical priority and diagnostic significance take precedence over anatomical order here.

=== STYLE GUIDANCE ===

{style_guidance}

=== RECOMMENDATIONS GUIDANCE ===

{recommendations_guidance}
"""
                
                # Add custom instructions if provided
                if custom_instructions:
                    impression_prompt += f"\n\n**Custom Instructions**: {custom_instructions}"
                
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
        
        # Generate report with new structured system
        model_name = "zai-glm-4.6"  # Primary model for structured templates
        provider = _get_model_provider(model_name)
        api_key = _get_api_key_for_provider(provider)
        
        if not api_key:
            raise ValueError(f"API key not configured for provider: {provider}")
        
        class ReportOutput(BaseModel):
            report_content: str
            description: str
            scan_type: str
        
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
                    "temperature": 0.3,
                    "top_p": 0.95,
                    "max_completion_tokens": 4096
                }
            )
            
            # Don't append signature yet - will append after validation
            report_output = result.output
            
            # LINGUISTIC VALIDATION for zai-glm-4.6 (conditionally enabled)
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
                "scan_type": report_output.scan_type
            }
        except Exception as e:
            # Check if it's a structured output timeout/error
            error_str = str(e).lower()
            is_structured_output_error = (
                'structured output' in error_str or
                'response_format' in error_str or
                'wrong_api_format' in error_str or
                '422' in error_str
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
                            "temperature": 0.3,
                            "top_p": 0.95,
                            "max_completion_tokens": 4096
                        }
                    )
                    
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
                    
                    # LINGUISTIC VALIDATION for zai-glm-4.6 (conditionally enabled)
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
                        report_content = _append_signature_to_report(report_content, user_signature)
                    
                    return {
                        "report_content": report_content,
                        "description": description,
                        "scan_type": scan_type
                    }
                except Exception as fallback_error:
                    print(f"[ERROR] Fallback parsing also failed: {fallback_error}")
                    raise ValueError(f"Failed to generate report with {model_name}: {str(e)}. Fallback also failed: {str(fallback_error)}")
            else:
                # Re-raise if it's not a structured output error
                raise

