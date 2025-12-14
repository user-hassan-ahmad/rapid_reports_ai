"""Template Manager for Custom Templates
Handles custom template operations similar to PromptManager but for user-created templates
"""
import re
from typing import Dict, List, Optional


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
    
    def render_template(
        self,
        template_content: str,
        variables: Dict[str, str]
    ) -> str:
        """
        Render a template with variable values
        
        Args:
            template_content: The template string with {{variables}}
            variables: Dictionary of variable names to values
            
        Returns:
            Rendered template string
        """
        result = template_content
        
        # Replace {{variable_name}} with actual values
        try:
            for var_name, var_value in variables.items():
                result = result.replace(f'{{{{{var_name}}}}}', var_value)
            return result
        except Exception as e:
            raise ValueError(f"Failed to render template: {str(e)}")
    
    def build_master_prompt(
        self,
        template: str,
        variable_values: Dict[str, str],
        template_name: Optional[str] = None,
        template_description: Optional[str] = None,
        master_instructions: Optional[str] = None,
        model: str = "claude"
    ) -> Dict[str, str]:
        """
        Build system and user prompts following best practices.
        Model-agnostic implementation - works for all models.
        
        Args:
            template: The template content with variables
            variable_values: The values for each variable
            template_name: Optional template name for scan type extraction
            template_description: Optional template description for scan type extraction
            master_instructions: Optional custom instructions
            model: The model being used (for compatibility, not used in prompt generation)
            
        Returns:
            Dictionary with 'system_prompt' and 'user_prompt' keys
        """
        # Render the template with variables
        rendered_template = self.render_template(template, variable_values)
        
        # Extract FINDINGS and CLINICAL_HISTORY if present
        findings = variable_values.get('FINDINGS', '')
        clinical_history = variable_values.get('CLINICAL_HISTORY', '')
        
        # Build system prompt (persistent requirements)
        system_parts = []
        
        # System role
        system_parts.append("You are an expert NHS radiologist. Generate professional radiology reports using British English with flowing prose and logical anatomical progression.")
        system_parts.append("CRITICAL: You MUST use British English spelling and terminology throughout all output.")
        system_parts.append("")
        
        # Output format (persistent requirement)
        system_parts.append("OUTPUT FORMAT: You must provide structured JSON with three fields:")
        system_parts.append("- \"report_content\": The complete radiology report text WITH PROPER FORMATTING (use line breaks between sections, maintain paragraph structure)")
        system_parts.append("- \"description\": A brief 5-15 word summary of key findings for the history tab, max 150 characters (e.g., 'resolving subdural haematoma, no new abnormality' - do NOT repeat the scan type)")
        system_parts.append("- \"scan_type\": Extract the scan type and protocol combined from template name/description and findings context (e.g., 'CT head non-contrast', 'MRI brain with contrast'). Include contrast status ONLY if explicitly mentioned in template name/description or findings.")
        system_parts.append("")
        
        # Core constraints (persistent behavior)
        system_parts.append("CORE CONSTRAINTS:")
        system_parts.append("- TEMPLATE PRIORITY: The user's template structure and instructions take ABSOLUTE precedence. Follow the template exactly—all other rules are secondary")
        system_parts.append("- Section Headers: Include ALL section headers exactly as shown in the template (e.g., 'Findings:', 'Limitations:'). Use standard capitalization—do not use all caps (e.g., use 'Limitations:' not 'LIMITATIONS:')")
        system_parts.append("- No Hallucination: Include ONLY findings from <findings>—do not invent pathology")
        system_parts.append("- Protocol Consistency: Before reporting any finding, verify it is compatible with the scan protocol/type specified. Do NOT mention findings that require imaging techniques not performed in this scan (e.g., contrast enhancement on non-contrast scans, MRI signal characteristics on CT, diffusion-weighted findings on non-DWI sequences, perfusion parameters on non-perfusion scans, etc.). Cross-reference each finding against the scan type and protocol—if a finding cannot be assessed with the given protocol, exclude it from the report.")
        system_parts.append("- Writing Style: Adapt to the template style — use flowing prose with logical anatomical progression")
        system_parts.append("- No Duplication: Mention each finding once — do NOT create both Conclusion and Impression sections (they are synonymous)")
        system_parts.append("- CRITICAL - No Duplication: Each anatomical structure or finding mentioned ONCE ONLY—consolidate ALL information about each structure (appearance, contrast enhancement, signal characteristics, etc.) into ONE comprehensive statement")
        system_parts.append("- No Repetition: Do NOT repeat the same information using different wording or separate related findings about the same structure into different statements")
        system_parts.append("- Logical Consistency: Group all information about specific anatomy/pathology together—do NOT mention abnormal findings then later state the same structure is normal")
        system_parts.append("- Relevant Negatives: Include appropriate negative findings")
        system_parts.append("- Systematic Review: Include review of anatomy typically imaged for this scan type")
        system_parts.append("- Modality-Specific: Use appropriate terminology for the imaging modality")
        system_parts.append("- Direct Findings: Start Findings section directly with anatomical structures — AVOID introductory statements that repeat scan modality (e.g., 'The CT demonstrates...', 'On this scan...'). Begin with anatomical structures: 'The liver...', 'There is...', 'No...'")
        system_parts.append("- CRITICAL: Use ONLY the summary section name(s) specified in the template—never add extra summary sections")
        
        system_prompt = "\n".join(system_parts)
        
        # Build user prompt (task-specific)
        user_parts = []
        
        # Add input data (task-specific)
        if findings:
            user_parts.append("=== INPUT ===")
            user_parts.append("")
            user_parts.append("<findings>")
            user_parts.append(findings)
            user_parts.append("</findings>")
            user_parts.append("")
        
        if clinical_history:
            user_parts.append("<clinical_history>")
            user_parts.append(clinical_history)
            user_parts.append("</clinical_history>")
            user_parts.append("")
            user_parts.append("CRITICAL - CLINICAL QUESTION:")
            user_parts.append("- Extract the clinical question/presentation from clinical_history")
            user_parts.append("- FIRST Impression bullet MUST answer this directly and connect findings to symptoms/presentation")
            user_parts.append("")
        
        # Add master instructions if provided (task-specific customization)
        if master_instructions:
            user_parts.append("=== ADDITIONAL INSTRUCTIONS ===")
            user_parts.append(master_instructions)
            user_parts.append("")
        
        # Add the template structure (task-specific) - Show template FIRST
        user_parts.append("=== TEMPLATE STRUCTURE ===")
        user_parts.append(rendered_template)
        user_parts.append("")
        
        # Add template context for scan type extraction AFTER template structure
        # This ensures model sees template structure first, then uses context only for scan_type
        if template_name or template_description:
            user_parts.append("=== TEMPLATE CONTEXT (for scan_type extraction only) ===")
            if template_name:
                user_parts.append(f"Template Name: {template_name}")
            if template_description:
                user_parts.append(f"Template Description: {template_description}")
            user_parts.append("")
            user_parts.append("Use the template name/description above ONLY to extract scan_type for protocol validation. Do NOT use it to expand or modify report sections.")
            user_parts.append("Extract the scan type and protocol from the template name/description above, combined with findings context. Include contrast status ONLY if explicitly mentioned in template name/description or findings.")
            user_parts.append("")
        
        # Add variable summary (excluding FINDINGS and CLINICAL_HISTORY as they're already in structured sections)
        other_vars = {k: v for k, v in variable_values.items() if k not in ['FINDINGS', 'CLINICAL_HISTORY']}
        if other_vars:
            user_parts.append("### Additional Variable Values Provided")
            for var_name, var_value in other_vars.items():
                user_parts.append(f"- **{var_name}**: {var_value}")
            user_parts.append("")
        
        # Add task instructions
        user_parts.append("=== TASK ===")
        user_parts.append("Generate a complete, professional NHS-standard radiology report following the template structure above.")
        
        # Add structure guidance (task-specific)
        user_parts.append("")
        user_parts.append("=== STRUCTURE GUIDANCE ===")
        user_parts.append("CRITICAL: The report MUST include a Findings section, even if not explicitly shown in the template.")
        user_parts.append("If the template does not specify a Findings section, add one with the header 'Findings:' after Comparison/Limitations and before any summary section (Impression/Conclusion).")
        user_parts.append("The Findings section should contain the systematic anatomical review with positive findings and relevant negatives.")
        user_parts.append("")
        user_parts.append("Protocol Validation (CRITICAL):")
        user_parts.append("- Extract scan_type from template context and findings (include contrast status only if explicitly mentioned)")
        user_parts.append("- Before including ANY finding, verify it is compatible with the extracted scan_type/protocol")
        user_parts.append("- Do NOT report findings requiring imaging techniques not performed (e.g., contrast enhancement on non-contrast scans, DWI characteristics on non-DWI sequences, perfusion parameters on non-perfusion scans)")
        user_parts.append("- Cross-check each finding: \"Can this be evaluated with this scan type/protocol?\" If no, exclude it")
        user_parts.append("")
        user_parts.append("Findings Section Writing Style:")
        user_parts.append("- Note: Apply these principles where template is silent; template structure and instructions take precedence")
        user_parts.append("- Break into MULTIPLE paragraphs by logical anatomical groupings")
        user_parts.append("- Within each paragraph: positive findings first, then relevant negatives for that region")
        user_parts.append("- CRITICAL: Report significant/positive findings FIRST (acute > chronic, urgent > incidental)")
        user_parts.append("- THEN follow template's anatomical order for systematic coverage")
        user_parts.append("- Start directly with anatomical structures — do NOT use introductory statements that repeat the scan modality")
        user_parts.append("- AVOID: 'The CT demonstrates...', 'On this scan...', 'The abdominal CT shows...', 'This examination reveals...'")
        user_parts.append("- USE: Direct anatomical statements: 'The liver...', 'There is...', 'No...', 'Multiple...', etc.")
        user_parts.append("- Group related structures: 'The liver, spleen and pancreas are unremarkable'")
        user_parts.append("- Do NOT group unrelated regions: NOT 'The mediastinum, liver, adrenals and bones are unremarkable'")
        user_parts.append("- CRITICAL: Do NOT dump all normal findings into one massive sentence - distribute across appropriate paragraphs")
        user_parts.append("")
        user_parts.append("Logical Flow and Duplication Prevention:")
        user_parts.append("- Each structure/finding mentioned ONCE ONLY—consolidate all information about each structure (contrast enhancement, signal characteristics, measurements, etc.) into ONE comprehensive statement")
        user_parts.append("- Do NOT create separate statements that convey the same information using different wording")
        user_parts.append("- Group related structures together when they share the same status")
        user_parts.append("- Group all information about specific anatomy/pathology together—do NOT mention abnormal findings then later state the same structure is normal")
        user_parts.append("- After writing each sentence, check: \"Have I already stated this information?\" If yes, remove the duplicate")
        user_parts.append("- Review your entire Findings section before finalizing to ensure no information is repeated")
        user_parts.append("")
        user_parts.append("Standard report structure (if template doesn't specify otherwise):")
        user_parts.append("- Comparison: [prior imaging or 'No previous imaging available for comparison']")
        user_parts.append("- Limitations: [only if technical limitations exist, otherwise omit]")
        user_parts.append("- Findings: [MANDATORY - systematic anatomical review]")
        user_parts.append("- Impression/Conclusion: [summary section as specified by template]")
        user_parts.append("")
        user_parts.append("CRITICAL: If a section is NOT explicitly shown in the template structure above, keep it BRIEF and minimal. Only expand sections that are explicitly shown in the template.")
        user_parts.append("")
        user_parts.append("Comparison Section Guidance:")
        user_parts.append("- If Comparison is NOT in the template, keep it BRIEF (one sentence maximum)")
        user_parts.append("- Extract comparison info from findings if present (keywords: 'comparison', 'previous', 'prior')")
        user_parts.append("- Format: 'Compared with previous [modality] [region] [date if available]' OR 'No previous imaging available for comparison'")
        user_parts.append("- Do NOT expand Comparison section with detailed findings - save details for Findings section")
        user_parts.append("")
        
        # Add formatting guidance (task-specific)
        user_parts.append("")
        user_parts.append("=== FORMATTING GUIDANCE ===")
        user_parts.append("Adapt formatting to template requirements. General guidance:")
        user_parts.append("- Double line breaks (\\n\\n) between major sections unless template specifies otherwise")
        user_parts.append("- Single line breaks (\\n) between paragraphs within sections")
        user_parts.append("- Proper spacing with lists and bullet points")
        user_parts.append("- If signature is provided, use double line break (\\n\\n) before signature block")
        user_parts.append("- If Limitations present, typically place after Comparison and before Findings")
        user_parts.append("- Maintain paragraph structure appropriate to template style")
        user_parts.append("")
        user_parts.append("Section Header Consistency:")
        user_parts.append("- ALL section headers must be included as specified in the template (e.g., 'Findings:', 'Comparison:', 'Limitations:')")
        user_parts.append("- Use standard capitalization for section headers (e.g., 'Limitations:' not 'LIMITATIONS:' or 'LIMITATIONS')")
        user_parts.append("- Follow the exact header format shown in the template (with or without colon, capitalization style)")
        user_parts.append("- CRITICAL: Ensure 'Findings:' section header is always present, even if template omits it")
        
        # Add summary section guidance (task-specific)
        user_parts.append("")
        user_parts.append("=== SUMMARY SECTION GUIDANCE ===")
        user_parts.append("CRITICAL: Template may use 'Impression:', 'Conclusion:', or another name for the summary section. Use ONLY what the template specifies. Do NOT generate both—they are synonymous.")
        user_parts.append("")
        user_parts.append("Impression/Conclusion Section Requirements:")
        user_parts.append("- LENGTH: As concise as possible while diagnostically precise")
        user_parts.append("  • Target: 1-2 lines maximum")
        user_parts.append("  • Complex cases: 2-3 lines only if multiple unrelated urgent pathologies requiring distinct management")
        user_parts.append("  • If you have 3+ lines, STOP and reconsider: Are you listing related findings separately? Including incidentals? Over-segmenting?")
        user_parts.append("")
        user_parts.append("- CONTENT PRINCIPLES:")
        user_parts.append("  • Synthesize findings into diagnoses, don't list observations")
        user_parts.append("  • State conclusions directly - avoid 'suggestive of' unless genuinely uncertain")
        user_parts.append("  • First line: Diagnostic conclusion answering clinical question")
        user_parts.append("  • Second line (if urgent action needed): Specific actionable recommendation")
        user_parts.append("  • Remove all deletable words: verbose qualifiers, non-threshold measurements, hedging language")
        user_parts.append("  • One focused concept per line - don't mix unrelated findings")
        user_parts.append("")
        user_parts.append("- RELATED FINDINGS CONSOLIDATION:")
        user_parts.append("  • Findings that are manifestations of the same pathology = ONE diagnostic statement")
        user_parts.append("  • Do NOT create separate lines for related manifestations of the same disease process")
        user_parts.append("  • If findings are truly unrelated urgent pathologies requiring different management, they may warrant separate lines")
        user_parts.append("  • Question: 'Are these separate diseases or manifestations of one process?'")
        user_parts.append("")
        user_parts.append("- ACTIONABLE RECOMMENDATIONS IN IMPRESSION:")
        user_parts.append("  Include when: Urgent intervention required (biopsy, surgery, drain, referral), specific follow-up imaging needed (with timeframe/modality), immediate management change required")
        user_parts.append("  Format: Be specific - 'Urgent colonoscopic biopsy and oncologic MDT referral recommended' not 'Clinical correlation recommended'")
        user_parts.append("  Omit: Generic phrases ('clinical correlation', 'further evaluation' without specifics) unless genuinely uncertain about diagnosis")
        user_parts.append("  Critical: Do NOT omit urgent recommendations (e.g., biopsy for suspected malignancy, chest drain for tension pneumothorax, urgent MDT referral)")
        user_parts.append("")
        user_parts.append("  Scope of Practice - Radiologist Recommendations:")
        user_parts.append("  Within scope: Further imaging (specify modality/timeframe), urgent clinical review/referral to specific teams, tissue diagnosis (biopsy), immediate radiological interventions (drains, urgent MDT)")
        user_parts.append("  Beyond scope: Medication changes (starting/stopping drugs), definitive treatment decisions, clinical management beyond imaging")
        user_parts.append("  Format recommendations appropriately:")
        user_parts.append("    • 'Recommend urgent respiratory team review' NOT 'Recommend cessation of methotrexate'")
        user_parts.append("    • 'Recommend high-resolution CT for further characterisation' NOT 'Recommend drug cessation and HRCT'")
        user_parts.append("    • 'Findings raise concern for drug toxicity; recommend clinical correlation' NOT 'Stop medication'")
        user_parts.append("")
        user_parts.append("- INCIDENTAL FINDINGS IN IMPRESSION:")
        user_parts.append("  Include only if: requires urgent action, has malignant potential, needs specific follow-up/referral, at intervention threshold")
        user_parts.append("  Omit if: benign and common, below action thresholds, no follow-up needed")
        user_parts.append("  Decision rule: If it doesn't change immediate management, it doesn't belong in Impression")
        user_parts.append("  If a finding requires only routine surveillance or no further work-up, it belongs in Findings section, not Impression")
        user_parts.append("")
        user_parts.append("- Format: • [concise diagnostic conclusion or recommendation]")
        user_parts.append("- Before finalizing each line ask: 'Can a consultant say this more concisely?'")
        user_parts.append("- Before finalizing entire Impression ask: 'Do I have more than 2 lines? If yes, what can I consolidate or omit?'")
        user_parts.append("")
        user_parts.append("Findings vs Impression Distinction:")
        user_parts.append("- Findings section: Observational descriptions (what you see) - detailed measurements, appearances, locations")
        user_parts.append("- Impression section: Synthesis and interpretation (what it means clinically) - concise diagnostic conclusions, critical significance, actionable recommendations")
        
        # Add signature requirement - CONDITIONAL
        user_parts.append("")
        user_parts.append("**SIGNATURE HANDLING - CRITICAL:**")
        user_parts.append("- If {{SIGNATURE}} placeholder contains text, include it exactly as provided after the Impression/Conclusion section")
        user_parts.append("- If {{SIGNATURE}} placeholder is empty or has been removed, DO NOT add any signature, department name, \"Report generated by...\", or any other text after the Impression/Conclusion section")
        user_parts.append("- The report must end immediately after the Impression/Conclusion section if no signature is provided")
        user_parts.append("- DO NOT invent or hallucinate signatures, department names, or any closing text")
        user_parts.append("")
        user_parts.append("End your report with: {{SIGNATURE}}")
        user_parts.append("")
        
        # Add output purity instructions (CRITICAL - prevent input markers in output)
        user_parts.append("=== CRITICAL - OUTPUT PURITY ===")
        user_parts.append("- The report_content field must contain ONLY the radiology report sections (Comparison, Limitations if applicable, Findings, Impression/Conclusion, and Signature only if {{SIGNATURE}} placeholder contains text)")
        user_parts.append("- If {{SIGNATURE}} is empty or removed, report_content ends with Impression/Conclusion section - NO additional text")
        user_parts.append("- Do NOT include input markers like '<findings>', '<clinical_history>' or any XML tags")
        user_parts.append("- Do NOT include section headers like 'ORIGINAL FINDINGS:', 'INPUT:', or '=== INPUT ==='")
        user_parts.append("- Do NOT reference the input structure or echo back any part of the prompt")
        user_parts.append("- NO invented signatures, department names, or \"Report generated by...\" text")
        user_parts.append("")
        user_parts.append("Generate the report now:")
        
        user_prompt = "\n".join(user_parts)
        
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }
    
    def build_master_prompt_with_reasoning(
        self,
        template: str,
        variable_values: Dict[str, str],
        template_name: Optional[str] = None,
        template_description: Optional[str] = None,
        master_instructions: Optional[str] = None,
        model: str = "gpt-oss-120b"
    ) -> Dict[str, str]:
        """
        Build prompts with explicit reasoning phase for gpt-oss-120b.
        Uses principle-based approach for template adaptation.
        
        Args:
            template: The template content with variables
            variable_values: The values for each variable
            template_name: Optional template name for scan type extraction
            template_description: Optional template description for scan type extraction
            master_instructions: Optional custom instructions
            model: The model being used (for compatibility, defaults to gpt-oss-120b)
            
        Returns:
            Dictionary with 'system_prompt' and 'user_prompt' keys
        """
        # Render the template with variables
        rendered_template = self.render_template(template, variable_values)
        
        # Extract key variables
        findings = variable_values.get('FINDINGS', '')
        clinical_history = variable_values.get('CLINICAL_HISTORY', '')
        
        # Infer scan type from template context
        scan_type = template_name or template_description or "the scan type specified"
        
        # ========================================================================
        # SYSTEM PROMPT - Aligned with gptoss.json
        # ========================================================================
        
        system_parts = []
        
        system_parts.append("You are an expert NHS consultant radiologist with advanced clinical reasoning capabilities. You generate professional reports in British English following NHS standards.")
        system_parts.append("")
        system_parts.append("You work in TWO PHASES:")
        system_parts.append("1. REASONING: Internal clinical analysis (not shown to user)")
        system_parts.append("2. OUTPUT: Structured JSON report generation")
        system_parts.append("")
        system_parts.append("CRITICAL: All output must use British English spelling and terminology.")
        system_parts.append("")
        system_parts.append("OUTPUT FORMAT: You must provide structured JSON with three fields:")
        system_parts.append("- \"report_content\": Complete radiology report with proper formatting (use line breaks between sections, maintain paragraph structure)")
        system_parts.append("- \"description\": Brief 5-15 word summary for history tab (max 150 characters, exclude scan type)")
        system_parts.append("- \"scan_type\": Extract from template context and findings (include contrast status only if explicitly stated)")
        
        system_prompt = "\n".join(system_parts)
        
        # ========================================================================
        # USER PROMPT - Two Phases with Template Adaptation
        # ========================================================================
        
        user_parts = []
        
        # === INPUTS SECTION ===
        user_parts.append("=== INPUTS ===")
        user_parts.append("")
        user_parts.append(f"<scan_type>{scan_type}</scan_type>")
        user_parts.append(f"<clinical_history>{clinical_history}</clinical_history>")
        user_parts.append(f"<findings>{findings}</findings>")
        user_parts.append("")
        
        # === PHASE 1: CLINICAL REASONING (Steps 1-4 identical to gptoss.json) ===
        user_parts.append("=== PHASE 1: CLINICAL REASONING ===")
        user_parts.append("")
        user_parts.append("Before generating the report, systematically analyze the case:")
        user_parts.append("")
        user_parts.append("<reasoning>")
        user_parts.append("")
        
        # Step 1: Protocol Verification (unchanged from gptoss.json)
        user_parts.append("**Step 1: Protocol Verification**")
        user_parts.append("For EACH finding mentioned in <findings>:")
        user_parts.append("- State the finding")
        user_parts.append("- Ask: \"Is this finding detectable with the scan type?\"")
        user_parts.append("- Cross-check: Does this require imaging techniques NOT performed?")
        user_parts.append("  • Contrast enhancement features → requires contrast administration")
        user_parts.append("  • MRI signal characteristics (T1/T2/FLAIR/DWI) → requires MRI")
        user_parts.append("  • CT density/attenuation → requires CT")
        user_parts.append("  • Perfusion parameters → requires perfusion imaging")
        user_parts.append("  • Spectroscopy findings → requires MR spectroscopy")
        user_parts.append("- Decision: INCLUDE or EXCLUDE this finding")
        user_parts.append("- Create verified findings list")
        user_parts.append("")
        
        # Step 2: Clinical Question Extraction (unchanged from gptoss.json)
        user_parts.append("**Step 2: Clinical Question Extraction**")
        user_parts.append("- What is the specific indication from <clinical_history>?")
        user_parts.append("- What is the radiologist being asked to answer?")
        user_parts.append("- Note: This MUST be addressed first in the summary section")
        user_parts.append("")
        
        # Step 3: Anatomical Systematic Review
        user_parts.append("**Step 3: Anatomical Systematic Review**")
        user_parts.append("- List ALL structures visualized in this scan type")
        user_parts.append("- Which structures appear in <findings>? → Report these")
        user_parts.append("- Which structures NOT in <findings>? → Document as normal/unremarkable")
        user_parts.append("- **Plan logical anatomical groupings for flow**")
        user_parts.append("- **CRITICAL: Do NOT create one massive list of all normal structures at the end - distribute systematically across logical paragraphs**")
        user_parts.append("- **Ensure gastrointestinal tract review**: For abdominal/pelvic imaging, always comment on bowel (calibre, wall thickness, abnormal enhancement, obstruction etc.)")
        user_parts.append("")
        
        # Step 4: Clinical Significance & Impression Planning
        user_parts.append("**Step 4: Clinical Significance & Impression Planning**")
        user_parts.append("For verified findings:")
        user_parts.append("- What does this mean clinically? What's the differential diagnosis?")
        user_parts.append("- What's urgent/significant vs incidental?")
        user_parts.append("- What recommendations or follow-up needed?")
        user_parts.append("")
        user_parts.append("**Impression Synthesis Strategy:**")
        user_parts.append("- Can multiple findings be expressed as one diagnostic entity?")
        user_parts.append("- What's the irreducible diagnostic conclusion stripping all descriptive detail?")
        user_parts.append("- **Related Findings Analysis:**")
        user_parts.append("  • Are these findings manifestations of the same underlying pathology or disease process?")
        user_parts.append("  • If yes: Consolidate into single diagnostic statement - do NOT create separate lines for related manifestations")
        user_parts.append("  • If no: They may warrant separate lines only if they represent distinct urgent pathologies requiring different management")
        user_parts.append("- **Incidental Finding Triage:**")
        user_parts.append("  • INCLUDE if: requires urgent action, has malignant potential, needs specific follow-up/referral, at intervention threshold")
        user_parts.append("  • OMIT if: benign and common, below action thresholds, requires no follow-up, adequately noted in Findings")
        user_parts.append("  • Decision rule: If it doesn't change immediate management or require urgent action, it doesn't belong in Impression")
        user_parts.append("- How many lines needed? Simple case = 1-2 short lines; complex = 2-3 as justified")
        user_parts.append("- Remove every removable word: state diagnosis directly, avoid hedging, omit non-threshold measurements")
        user_parts.append("- **ORDERING STRATEGY: Plan to report significant findings FIRST, then follow template structure for systematic coverage**")
        user_parts.append("")
        
        # Step 5: Template Structure Analysis & Comparison Evidence Check
        user_parts.append("**Step 5: Template Structure Analysis & Comparison Evidence Check**")
        user_parts.append("The user has provided a template that may contain:")
        user_parts.append("- Structural elements (section organization)")
        user_parts.append("- Content guidance (what/how to describe)")
        user_parts.append("- Formatting preferences (style, length, bullets)")
        user_parts.append("")
        user_parts.append("Analyze the template below and determine:")
        user_parts.append("1. What sections/structure has the user explicitly defined?")
        user_parts.append("2. What content organization guidance has the user provided?")
        user_parts.append("3. What aspects are undefined and need standard conventions?")
        user_parts.append("")
        user_parts.append("Synthesis principle:")
        user_parts.append("User's explicit guidance = ABSOLUTE PRIORITY")
        user_parts.append("Undefined elements = Fill with professional radiology standards")
        user_parts.append("")
        user_parts.append("Plan your report structure synthesis:")
        user_parts.append("- [State your interpretation of the template type and structure]")
        user_parts.append("- [Identify what's explicit vs what needs fallback]")
        user_parts.append("- [Formulate your final section order and content strategy]")
        user_parts.append("")
        user_parts.append("**CRITICAL - Comparison Evidence Verification:**")
        user_parts.append("")
        user_parts.append("For EACH significant finding that will appear in Impression:")
        user_parts.append("1. Verify: 'Is THIS SPECIFIC FINDING explicitly described with comparison terminology in <findings>?'")
        user_parts.append("   - Comparison indicators: unchanged, stable, as previously seen, increased, decreased, new, interval change, compared to, persists")
        user_parts.append("2. If explicit comparison exists → Use matching terminology in Impression")
        user_parts.append("3. If NO comparison exists → Assess clinical context:")
        user_parts.append("   - Acute clinical presentation → Describe as acute or new")
        user_parts.append("   - Chronic or incidental finding → Use neutral descriptive language only")
        user_parts.append("   - NEVER apply temporal comparison terms without explicit evidence in <findings>")
        user_parts.append("")
        
        user_parts.append("</reasoning>")
        user_parts.append("")
        
        # === USER'S TEMPLATE ===
        user_parts.append("=== USER'S TEMPLATE ===")
        user_parts.append("")
        user_parts.append(rendered_template)
        user_parts.append("")
        
        # Add template context if provided
        if template_name or template_description:
            user_parts.append("=== TEMPLATE CONTEXT ===")
            if template_name:
                user_parts.append(f"Template Name: {template_name}")
            if template_description:
                user_parts.append(f"Description: {template_description}")
            user_parts.append("")
            user_parts.append("Use context above only for scan_type extraction and protocol validation.")
            user_parts.append("")
        
        # Add master instructions if provided
        if master_instructions:
            user_parts.append("=== ADDITIONAL INSTRUCTIONS ===")
            user_parts.append(master_instructions)
            user_parts.append("")
        
        # === PHASE 2: REPORT GENERATION (Template-adapted) ===
        user_parts.append("=== PHASE 2: REPORT GENERATION ===")
        user_parts.append("")
        user_parts.append("Now generate the structured radiology report following these principles:")
        user_parts.append("")
        
        # Core principles (aligned with gptoss.json but adapted for templates)
        user_parts.append("**CORE PRINCIPLES:**")
        user_parts.append("")
        user_parts.append("1. TEMPLATE PRIORITY:")
        user_parts.append("   The user's template structure and guidance take ABSOLUTE precedence.")
        user_parts.append("   Follow the template's explicit elements exactly.")
        user_parts.append("")
        user_parts.append("2. INTELLIGENT INTEGRATION:")
        user_parts.append("   Where template is silent, apply professional radiology standards:")
        user_parts.append("   • Standard section flow: Comparison → Limitations (if present) → Findings → Impression")
        user_parts.append("   • Standard Findings style: Direct anatomical statements, systematic coverage, no duplication")
        user_parts.append("   • Standard Impression: 2-4 synthesis bullets, clinical question first")
        user_parts.append("")
        user_parts.append("3. PROTOCOL CONSISTENCY:")
        user_parts.append("   Before reporting any finding, verify it's compatible with scan type/protocol.")
        user_parts.append("   Do NOT mention findings requiring techniques not performed.")
        user_parts.append("")
        user_parts.append("4. NO HALLUCINATION:")
        user_parts.append("   Include ONLY findings from <findings>—do not invent pathology.")
        user_parts.append("")
        user_parts.append("5. NO DUPLICATION:")
        user_parts.append("   Each anatomical structure mentioned ONCE only—consolidate all information.")
        user_parts.append("")
        user_parts.append("6. FINDINGS vs IMPRESSION DISTINCTION:")
        user_parts.append("   Findings = Observational (what you see)")
        user_parts.append("   Impression = Synthesis (what it means clinically)")
        user_parts.append("")
        user_parts.append("7. CLINICAL PRIORITY WITHIN TEMPLATE STRUCTURE:")
        user_parts.append("   CRITICAL: Report significant/positive findings FIRST within each template section.")
        user_parts.append("   Within Findings section: Start with acute/urgent/significant pathology, then follow template's anatomical order for systematic coverage.")
        user_parts.append("   Template structure defines WHAT to cover and HOW to organize—clinical priority determines ORDER within that structure.")
        user_parts.append("   Example: If template says 'brain parenchyma first' but there's an acute subdural, report the subdural first, then brain parenchyma findings.")
        user_parts.append("")
        
        # Standard fallback guidance (succinct, principle-based)
        user_parts.append("**STANDARD CONVENTIONS (apply where template is undefined):**")
        user_parts.append("")
        user_parts.append("Section Structure:")
        user_parts.append("• Comparison: Extract from <findings> OR 'No previous imaging available for comparison'")
        user_parts.append("• Limitations: Only if technical issues exist in <findings>, otherwise omit")
        user_parts.append("• Findings: Systematic anatomical review—start directly with anatomy, break into paragraphs by region")
        user_parts.append("• Impression: 1-2 lines maximum, first answers clinical question, synthesis not repetition")
        user_parts.append("")
        user_parts.append("Findings Section Style:")
        user_parts.append("• Note: Apply these principles where template is silent; template structure and instructions take precedence")
        user_parts.append("• Break into MULTIPLE paragraphs by logical anatomical groupings")
        user_parts.append("• Within each paragraph: positive findings first, then relevant negatives for that region")
        user_parts.append("• Start with significant/positive findings FIRST (acute > chronic, urgent > incidental)")
        user_parts.append("• THEN follow template's anatomical order for systematic coverage")
        user_parts.append("• Start directly: 'The liver...', 'There is...', 'No...'")
        user_parts.append("• NOT: 'The CT demonstrates...', 'On this scan...', 'Imaging shows...'")
        user_parts.append("• Group related structures: 'The liver, spleen and pancreas are unremarkable'")
        user_parts.append("• Do NOT group unrelated regions: NOT 'The mediastinum, liver, adrenals and bones are unremarkable'")
        user_parts.append("• CRITICAL: Do NOT dump all normal findings into one massive sentence - distribute across appropriate paragraphs")
        user_parts.append("• Multiple paragraphs with single line breaks (\\n)")
        user_parts.append("• Modality-specific language: CT = density/attenuation; MRI = signal intensity")
        user_parts.append("")
        user_parts.append("Impression Section Style:")
        user_parts.append("• LENGTH: Target 1-2 lines maximum; 2-3 only if multiple unrelated urgent pathologies requiring distinct management")
        user_parts.append("  - If 3+ lines, STOP and reconsider: Are you listing related findings separately? Including incidentals? Over-segmenting?")
        user_parts.append("• CONTENT: Synthesize findings into diagnoses, state conclusions directly, remove all deletable words")
        user_parts.append("• RELATED FINDINGS: Manifestations of same pathology = ONE diagnostic statement; do NOT create separate lines for related manifestations")
        user_parts.append("• First line: Answer clinical question with diagnostic conclusion by synthesizing findings")
        user_parts.append("• Second line (if urgent action needed): Specific actionable recommendation (biopsy, intervention, referral, follow-up imaging with timeframe)")
        user_parts.append("• RECOMMENDATIONS: Include urgent recommendations; be specific not generic; do NOT omit critical recommendations (e.g., biopsy for malignancy, drain for tension pneumothorax)")
        user_parts.append("• SCOPE OF PRACTICE: Recommendations must stay within radiology scope (imaging, referrals, biopsies) - do NOT recommend medication changes or treatment decisions")
        user_parts.append("  - Use: 'Recommend urgent respiratory team review' NOT 'Recommend cessation of methotrexate'")
        user_parts.append("  - Use: 'Recommend high-resolution CT' NOT 'Recommend drug cessation and HRCT'")
        user_parts.append("• INCIDENTAL FINDINGS: Include only if urgent action/malignant potential/specific follow-up needed; omit benign/common findings")
        user_parts.append("  - If finding requires only routine surveillance or no further work-up, it belongs in Findings, not Impression")
        user_parts.append("• Before finalizing each line ask: 'Can a consultant say this more concisely?'")
        user_parts.append("• Before finalizing entire Impression ask: 'Do I have more than 2 lines? If yes, what can I consolidate or omit?'")
        user_parts.append("")
        user_parts.append("**COMPARISON TERMINOLOGY RULES:**")
        user_parts.append("• Temporal comparison terms (stable/unchanged/increased/decreased/new/persists/interval) require explicit comparison evidence in <findings>")
        user_parts.append("• Without comparison evidence: use neutral descriptive language or context-appropriate terms (acute for trauma/emergency presentations)")
        user_parts.append("• Do NOT assume prior imaging covered all anatomical regions of current study")
        user_parts.append("")
        
        # Formatting guidance (aligned with gptoss.json)
        user_parts.append("**FORMATTING REQUIREMENTS:**")
        user_parts.append("• Double line breaks (\\n\\n) between major sections")
        user_parts.append("• Single line breaks (\\n) within Findings to separate anatomical paragraphs")
        user_parts.append("• Section headers in bold: **Comparison:**, **Limitations:**, **Findings:**, **Impression:**")
        user_parts.append("• Bullet points in Impression: • [text]")
        user_parts.append("• Adapt to template's formatting preferences if specified")
        user_parts.append("")
        
        # Signature - CONDITIONAL HANDLING
        user_parts.append("**SIGNATURE HANDLING - CRITICAL:**")
        user_parts.append("• If {{SIGNATURE}} placeholder contains text, include it exactly as provided after the Impression section")
        user_parts.append("• If {{SIGNATURE}} placeholder is empty or has been removed, DO NOT add any signature, department name, \"Report generated by...\", or any other text after the Impression section")
        user_parts.append("• The report must end immediately after the Impression section if no signature is provided")
        user_parts.append("• DO NOT invent or hallucinate signatures, department names, or any closing text")
        user_parts.append("")
        user_parts.append("{{SIGNATURE}}")
        user_parts.append("")
        
        # Output purity (updated to handle conditional signature)
        user_parts.append("**OUTPUT PURITY - CRITICAL:**")
        user_parts.append("• report_content contains ONLY: report sections (Comparison, Limitations if applicable, Findings, Impression, and Signature only if {{SIGNATURE}} placeholder contains text)")
        user_parts.append("• If {{SIGNATURE}} is empty or removed, report_content ends with Impression section - NO additional text")
        user_parts.append("• NO XML tags (<findings>, <scan_type>, etc.)")
        user_parts.append("• NO input markers or prompt structure")
        user_parts.append("• NO section headers like 'INPUTS:', 'REASONING:', '=== PHASE ==='")
        user_parts.append("• NO references to the prompt or input structure")
        user_parts.append("• NO invented signatures, department names, or \"Report generated by...\" text")
        user_parts.append("")
        
        # Quality checklist (streamlined from gptoss.json)
        user_parts.append("**QUALITY VERIFICATION:**")
        user_parts.append("Before finalizing, confirm:")
        user_parts.append("✓ All findings are protocol-compatible (verified in reasoning phase)")
        user_parts.append("✓ No invented pathology - only findings from <findings>")
        user_parts.append("✓ All visualized structures documented (positive findings + systematic negatives)")
        user_parts.append("✓ Clinical question answered in first Impression bullet")
        user_parts.append("✓ User's template guidance respected absolutely")
        user_parts.append("✓ No duplication of information")
        user_parts.append("✓ Correct modality-specific terminology")
        user_parts.append("✓ British English throughout")
        user_parts.append("✓ Comparison terms only used when explicit comparison evidence exists in <findings> or clinical context indicates acute/new pathology")
        user_parts.append("✓ Valid JSON output")
        user_parts.append("")
        
        user_parts.append("=== GENERATE REPORT NOW ===")
        
        user_prompt = "\n".join(user_parts)
        
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }

