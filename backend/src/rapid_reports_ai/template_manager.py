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
    
    def build_unified_master_prompt(
        self,
        template: str,
        variable_values: Dict[str, str],
        template_name: Optional[str] = None,
        template_description: Optional[str] = None,
        master_instructions: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Unified prompt builder optimized for gpt-oss-120b reasoning model.
        Extracts successful patterns from quick reports (gptoss.json) while maintaining 
        template flexibility for user customization.
        
        Core principle: Template Priority with Best Practice Foundation
        - User's explicit template structure = ABSOLUTE PRIORITY
        - Where template is silent = Apply proven quick reports principles (5 critical rules)
        - Always uses reasoning approach (optimized for gpt-oss-120b)
        
        Args:
            template: The template content with variables
            variable_values: The values for each variable
            template_name: Optional template name for scan type extraction
            template_description: Optional template description for scan type extraction
            master_instructions: Optional custom instructions
            
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
        # SYSTEM PROMPT - Concise, aligned with gptoss.json
        # ========================================================================
        
        system_parts = []
        system_parts.append("You are an expert NHS consultant radiologist with advanced clinical reasoning capabilities. You generate professional reports in British English following NHS standards.")
        system_parts.append("")
        system_parts.append("You work in TWO PHASES:")
        system_parts.append("1. REASONING: Internal clinical analysis and structure planning")
        system_parts.append("2. GENERATION: Structured JSON report generation with strict adherence to 5 critical rules")
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
        
        # === CASE DATA ===
        user_parts.append("=== CASE DATA ===")
        user_parts.append(f"<scan_type>{scan_type}</scan_type>")
        user_parts.append(f"<clinical_history>{clinical_history}</clinical_history>")
        user_parts.append(f"<findings>{findings}</findings>")
        user_parts.append("")
        
        # === PHASE 1: CLINICAL REASONING ===
        user_parts.append("=== PHASE 1: CLINICAL REASONING ===")
        user_parts.append("")
        user_parts.append("Systematically analyze the case before writing:")
        user_parts.append("")
        
        # Step 1: Template Structure Analysis (NEW - template-specific)
        user_parts.append("**Step 1: Template Structure Analysis**")
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
        user_parts.append("Undefined elements = Fill with professional radiology standards (5 critical rules)")
        user_parts.append("")
        user_parts.append("Plan your report structure synthesis:")
        user_parts.append("- [State your interpretation of the template type and structure]")
        user_parts.append("- [Identify what's explicit vs what needs fallback]")
        user_parts.append("- [Formulate your final section order and content strategy]")
        user_parts.append("")
        
        # Step 2: Protocol Verification (from gptoss.json)
        user_parts.append("**Step 2: Protocol Verification**")
        user_parts.append("For EACH finding mentioned in <findings>:")
        user_parts.append("1. Is this finding valid for the scan type? (e.g., CT non-contrast cannot show enhancement, CT cannot describe signal intensity, MRI cannot describe attenuation)")
        user_parts.append("2. Cross-check: Does this require imaging techniques NOT performed?")
        user_parts.append("   • Contrast enhancement features → requires contrast administration")
        user_parts.append("   • MRI signal characteristics (T1/T2/FLAIR/DWI) → requires MRI")
        user_parts.append("   • CT density/attenuation → requires CT")
        user_parts.append("   • Perfusion parameters → requires perfusion imaging")
        user_parts.append("   • Spectroscopy findings → requires MR spectroscopy")
        user_parts.append("3. Decision: INCLUDE or EXCLUDE this finding")
        user_parts.append("4. Create verified findings list")
        user_parts.append("")
        
        # Step 3: Clinical Question & Significance
        user_parts.append("**Step 3: Clinical Question & Significance**")
        user_parts.append("• Clinical question: What is being asked from <clinical_history>?")
        user_parts.append("• Prior imaging: Extract modality, date, region (if mentioned in <findings>)")
        user_parts.append("• Limitations: Technical factors affecting interpretation (if any)")
        user_parts.append("")
        user_parts.append("For each verified finding:")
        user_parts.append("- Clinical significance: Urgent/significant vs incidental?")
        user_parts.append("- Which anatomical region/system?")
        user_parts.append("- Key differentials?")
        user_parts.append("- Pertinent negatives relevant to these differentials?")
        user_parts.append("")
        
        # Step 4: Anatomical Scope & Structure Planning
        user_parts.append("**Step 4: Anatomical Scope & Structure Planning**")
        user_parts.append("• List ALL anatomical regions visible on this scan type including scan extremities")
        user_parts.append("• Which structures appear in <findings>? → Report these")
        user_parts.append("• Which structures NOT in <findings>? → Document as normal/unremarkable")
        user_parts.append("")
        user_parts.append("PATHOLOGY PARAGRAPHS (if pathology present):")
        user_parts.append("• Paragraph 1: [pathology name] → immediate complications → pertinent negatives → affected structures")
        user_parts.append("• Paragraph 2: [if additional pathology] → ...")
        user_parts.append("")
        user_parts.append("REMAINING ANATOMY PARAGRAPHS:")
        user_parts.append("• Group 1: [System, e.g., \"solid organs\"] → 1-2 sentences covering liver, spleen, pancreas, etc.")
        user_parts.append("• Group 2: [System, e.g., \"hollow viscera\"] → 1-2 sentences covering bowel, bladder, etc.")
        user_parts.append("• Target: Maximum 2-3 sentences per group")
        user_parts.append("")
        user_parts.append("**CRITICAL: Do NOT create one massive list of all normal structures at the end - distribute systematically across logical paragraphs**")
        user_parts.append("**Ensure gastrointestinal tract review**: For abdominal/pelvic imaging, always comment on bowel (calibre, wall thickness, abnormal enhancement, obstruction etc.)")
        user_parts.append("")
        user_parts.append("Apply template structure where specified:")
        user_parts.append("- If template defines section order → Follow it")
        user_parts.append("- If template defines anatomical order → Follow it")
        user_parts.append("- If template is silent → Use standard radiology conventions")
        user_parts.append("")
        
        # Step 5: Impression Planning
        user_parts.append("**Step 5: Impression Planning**")
        user_parts.append("• Main diagnostic conclusion: [one sentence]")
        user_parts.append("• Significant/actionable incidentals ONLY (those requiring intervention, follow-up, or referral): [if any, one sentence or omit]")
        user_parts.append("• Recommendation (only if non-obvious): [one sentence or omit]")
        user_parts.append("")
        user_parts.append("EXCLUDE: Benign incidentals below action threshold (simple cysts, benign haemangiomas, etc. that require no follow-up)")
        user_parts.append("")
        user_parts.append("**Related Findings Analysis:**")
        user_parts.append("• Are these findings manifestations of the same underlying pathology or disease process?")
        user_parts.append("• If yes: Consolidate into single diagnostic statement - do NOT create separate lines for related manifestations")
        user_parts.append("• If no: They may warrant separate lines only if they represent distinct urgent pathologies requiring different management")
        user_parts.append("")
        user_parts.append("**Comparison Evidence Verification:**")
        user_parts.append("For EACH significant finding that will appear in Impression:")
        user_parts.append("1. Verify: 'Is THIS SPECIFIC FINDING explicitly described with comparison terminology in <findings>?'")
        user_parts.append("   - Comparison indicators: unchanged, stable, as previously seen, increased, decreased, new, interval change, compared to, persists")
        user_parts.append("2. If explicit comparison exists → Use matching terminology in Impression")
        user_parts.append("3. If NO comparison exists → Assess clinical context:")
        user_parts.append("   - Acute clinical presentation → Describe as acute or new")
        user_parts.append("   - Chronic or incidental finding → Use neutral descriptive language only")
        user_parts.append("   - NEVER apply temporal comparison terms without explicit evidence in <findings>")
        user_parts.append("")
        
        # Verification Checklist (from gptoss.json)
        user_parts.append("VERIFICATION CHECKLIST (CHECK BEFORE WRITING):")
        user_parts.append("□ All regions from anatomical scope covered?")
        user_parts.append("□ Each structure mentioned only ONCE?")
        user_parts.append("□ Pertinent negatives integrated WITH pathology (not repeated separately)?")
        user_parts.append("□ Related normal structures grouped together?")
        user_parts.append("□ Template guidance respected where specified?")
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
        
        # === PHASE 2: REPORT GENERATION ===
        user_parts.append("=== PHASE 2: REPORT GENERATION ===")
        user_parts.append("")
        user_parts.append("Generate the report following these principles:")
        user_parts.append("")
        
        # Template Priority Principle
        user_parts.append("**TEMPLATE PRIORITY PRINCIPLE:**")
        user_parts.append("1. User's explicit template structure and guidance = ABSOLUTE PRECEDENCE")
        user_parts.append("2. Master instructions field (if provided) = High priority customization")
        user_parts.append("3. Where template is silent = Apply 5 CRITICAL RULES below")
        user_parts.append("4. Standard NHS conventions = Fallback for undefined elements")
        user_parts.append("")
        
        # 5 Critical Rules (from gptoss.json)
        user_parts.append("**5 CRITICAL RULES (apply where template is silent):**")
        user_parts.append("")
        user_parts.append("**RULE 1: ONE MENTION ONLY**")
        user_parts.append("Each anatomical structure appears ONCE in the entire report.")
        user_parts.append("")
        user_parts.append("❌ BAD: \"The liver is unremarkable. ... The liver, spleen and pancreas are unremarkable.\"")
        user_parts.append("✅ GOOD: \"The liver, spleen and pancreas are unremarkable.\"")
        user_parts.append("")
        user_parts.append("**RULE 2: GROUP, DON'T LIST**")
        user_parts.append("Combine related normal structures into single sentences.")
        user_parts.append("")
        user_parts.append("❌ BAD: \"The liver is unremarkable. The gallbladder is unremarkable. The spleen is unremarkable. The pancreas is unremarkable.\"")
        user_parts.append("✅ GOOD: \"The solid abdominal organs are unremarkable.\"")
        user_parts.append("")
        user_parts.append("**RULE 3: INTEGRATE PERTINENT NEGATIVES**")
        user_parts.append("Pertinent negatives belong WITH the pathology they relate to, not separately.")
        user_parts.append("")
        user_parts.append("❌ BAD: \"There is a 3 cm liver lesion. No biliary dilatation. No ascites. ... [Later:] The bile ducts are not dilated.\"")
        user_parts.append("✅ GOOD: \"There is a 3 cm liver lesion without biliary dilatation or ascites.\"")
        user_parts.append("")
        user_parts.append("**RULE 4: SENTENCE LENGTH LIMITS**")
        user_parts.append("• Pathology sentences: Maximum 30 words")
        user_parts.append("• Normal anatomy sentences: Maximum 20 words")
        user_parts.append("• If describing complex pathology, use 2 shorter sentences instead of 1 long sentence")
        user_parts.append("")
        user_parts.append("**RULE 5: IMPRESSION = DIAGNOSIS + ACTION ONLY**")
        user_parts.append("Impression is 1-2 sentences in prose format (NOT bullet points):")
        user_parts.append("• Main diagnostic conclusion or differential diagnosis")
        user_parts.append("• Significant/actionable incidental findings ONLY (those requiring intervention, follow-up, referral, or with malignant potential)")
        user_parts.append("• Recommendations (only if non-obvious: MDT, biopsy, interval imaging, urgent referral)")
        user_parts.append("")
        user_parts.append("DO NOT include benign incidentals below action threshold (e.g., simple renal cysts <1cm, small liver haemangiomas, benign-appearing nodules that require no follow-up).")
        user_parts.append("")
        user_parts.append("CRITICAL: State conclusions DIRECTLY. Do NOT use explanatory phrases like \"indicating\", \"demonstrating\", \"consistent with\", \"suggesting\" - these add verbosity. Do NOT restate what was already said - if you said \"no metastases\", don't add \"indicating no metastatic disease\".")
        user_parts.append("")
        user_parts.append("❌ BAD: \"No pulmonary metastases or mediastinal lymphadenopathy identified, indicating no evidence of thoracic metastatic disease.\" (redundant)")
        user_parts.append("✅ GOOD: \"No evidence of thoracic metastatic disease.\" (concise, direct conclusion)")
        user_parts.append("")
        
        # Standard Conventions (where template is undefined)
        user_parts.append("**STANDARD CONVENTIONS (apply where template is undefined):**")
        user_parts.append("")
        user_parts.append("Section Structure:")
        user_parts.append("• Comparison: Extract from <findings> OR 'No previous imaging available for comparison'")
        user_parts.append("• Limitations: Only if technical issues exist in <findings>, otherwise omit")
        user_parts.append("• Findings: MANDATORY - systematic anatomical review, start directly with anatomy")
        user_parts.append("• Impression/Conclusion: As specified by template (or 'Impression:' if template silent)")
        user_parts.append("")
        user_parts.append("Findings Section Style (where template is silent):")
        user_parts.append("• Break into MULTIPLE paragraphs by logical anatomical groupings")
        user_parts.append("• Within each paragraph: positive findings first, then relevant negatives for that region")
        user_parts.append("• Start with significant/positive findings FIRST (acute > chronic, urgent > incidental)")
        user_parts.append("• THEN follow template's anatomical order for systematic coverage (if template specifies)")
        user_parts.append("• Start directly: 'The liver...', 'There is...', 'No...'")
        user_parts.append("• NOT: 'The CT demonstrates...', 'On this scan...', 'Imaging shows...'")
        user_parts.append("• Group related structures: 'The liver, spleen and pancreas are unremarkable'")
        user_parts.append("• Do NOT group unrelated regions: NOT 'The mediastinum, liver, adrenals and bones are unremarkable'")
        user_parts.append("• CRITICAL: Do NOT dump all normal findings into one massive sentence - distribute across appropriate paragraphs")
        user_parts.append("• Multiple paragraphs with single line breaks (\\n)")
        user_parts.append("• Modality-specific language: CT = density/attenuation; MRI = signal intensity")
        user_parts.append("")
        user_parts.append("Impression Section Style (where template is silent):")
        user_parts.append("• LENGTH: Target 1-2 lines maximum; 2-3 only if multiple unrelated urgent pathologies requiring distinct management")
        user_parts.append("• CONTENT: Synthesize findings into diagnoses, state conclusions directly, remove all deletable words")
        user_parts.append("• RELATED FINDINGS: Manifestations of same pathology = ONE diagnostic statement")
        user_parts.append("• First line: Answer clinical question with diagnostic conclusion")
        user_parts.append("• Second line (if urgent action needed): Specific actionable recommendation")
        user_parts.append("• RECOMMENDATIONS: Include urgent recommendations; be specific not generic")
        user_parts.append("• SCOPE OF PRACTICE: Recommendations must stay within radiology scope (imaging, referrals, biopsies)")
        user_parts.append("  - Use: 'Recommend urgent respiratory team review' NOT 'Recommend cessation of methotrexate'")
        user_parts.append("• INCIDENTAL FINDINGS: Include only if urgent action/malignant potential/specific follow-up needed")
        user_parts.append("")
        
        # Formatting Requirements
        user_parts.append("**FORMATTING REQUIREMENTS:**")
        user_parts.append("• Double line breaks (\\n\\n) between major sections")
        user_parts.append("• Single line breaks (\\n) within Findings to separate anatomical paragraphs")
        user_parts.append("• Section headers: Follow template format (or bold: **Comparison:**, **Limitations:**, **Findings:**, **Impression:** if template silent)")
        user_parts.append("• Impression: Prose format (flowing sentences), NOT bullet points (unless template specifies bullets)")
        user_parts.append("• Adapt to template's formatting preferences if specified")
        user_parts.append("")
        
        # Signature Handling
        user_parts.append("**SIGNATURE HANDLING - CRITICAL:**")
        user_parts.append("• If {{SIGNATURE}} placeholder contains text, include it exactly as provided after the Impression/Conclusion section")
        user_parts.append("• If {{SIGNATURE}} placeholder is empty or has been removed, DO NOT add any signature, department name, \"Report generated by...\", or any other text")
        user_parts.append("• The report must end immediately after the Impression/Conclusion section if no signature is provided")
        user_parts.append("• DO NOT invent or hallucinate signatures, department names, or any closing text")
        user_parts.append("")
        user_parts.append("{{SIGNATURE}}")
        user_parts.append("")
        
        # Output Purity
        user_parts.append("**OUTPUT PURITY - CRITICAL:**")
        user_parts.append("• report_content contains ONLY: report sections (Comparison, Limitations if applicable, Findings, Impression/Conclusion, and Signature only if {{SIGNATURE}} placeholder contains text)")
        user_parts.append("• If {{SIGNATURE}} is empty or removed, report_content ends with Impression/Conclusion section - NO additional text")
        user_parts.append("• NO XML tags (<findings>, <scan_type>, etc.)")
        user_parts.append("• NO input markers or prompt structure")
        user_parts.append("• NO section headers like 'INPUTS:', 'REASONING:', '=== PHASE ==='")
        user_parts.append("• NO references to the prompt or input structure")
        user_parts.append("• NO invented signatures, department names, or \"Report generated by...\" text")
        user_parts.append("")
        
        # Mandatory Self-Check (from gptoss.json)
        user_parts.append("**BEFORE OUTPUTTING - MANDATORY SELF-CHECK:**")
        user_parts.append("")
        user_parts.append("□ Did I mention any anatomical structure more than once? (Re-read and verify)")
        user_parts.append("□ Are all sentences under the word limit? (Count: pathology ≤30 words, normal anatomy ≤20 words)")
        user_parts.append("□ Is my impression diagnostic conclusions only? (No descriptive details from Findings, no benign incidentals below threshold, no redundant explanatory phrases like \"indicating\" or \"demonstrating\")")
        user_parts.append("□ Did I group related normal structures together? (Not listed individually)")
        user_parts.append("□ Are pertinent negatives integrated WITH pathology? (Not repeated separately)")
        user_parts.append("□ Did I respect the template structure where specified?")
        user_parts.append("□ Did I apply the 5 critical rules where template was silent?")
        user_parts.append("")
        user_parts.append("If you found ANY issues in this self-check, FIX THEM NOW before outputting JSON.")
        user_parts.append("")
        user_parts.append("=== GENERATE REPORT NOW ===")
        
        user_prompt = "\n".join(user_parts)
        
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }
