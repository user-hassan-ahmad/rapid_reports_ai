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
    
    def _build_simple_prompt_for_zai_glm(
        self,
        template: str,
        variable_values: Dict[str, str],
        template_name: Optional[str] = None,
        template_description: Optional[str] = None,
        master_instructions: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Simpler prompt builder for zai-glm-4.6 model.
        Uses direct instructions without complex reasoning phases.
        
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
        # SYSTEM PROMPT - Simple and direct
        # ========================================================================
        system_prompt = """You are an expert NHS consultant radiologist generating professional radiology reports in British English following NHS standards.

CRITICAL: All output must use British English spelling and terminology (e.g., oesophagus, haemorrhage, oedema, paediatric).

OUTPUT FORMAT: You must provide structured JSON with three fields:
- "report_content": Complete radiology report following the template structure provided
- "description": Brief 5-15 word summary for history tab (max 150 characters, exclude scan type)
- "scan_type": Extract from template context and findings (include contrast status only if explicitly stated)"""
        
        # ========================================================================
        # USER PROMPT - Direct and clear
        # ========================================================================
        user_parts = []
        
        user_parts.append("=== CASE INFORMATION ===")
        user_parts.append(f"Scan Type: {scan_type}")
        user_parts.append(f"Clinical History: {clinical_history}")
        user_parts.append(f"Findings: {findings}")
        user_parts.append("")
        
        user_parts.append("=== TEMPLATE STRUCTURE TO FOLLOW ===")
        user_parts.append("")
        user_parts.append("The template below shows the STRUCTURE and FORMAT you should use for your report.")
        user_parts.append("CRITICAL: Do NOT return the template itself. Instead, GENERATE a report using this structure.")
        user_parts.append("")
        user_parts.append("Instructions:")
        user_parts.append("1. Follow the template's section organization and formatting")
        user_parts.append("2. Replace template placeholders and example text with actual findings from the case")
        user_parts.append("3. Remove or replace 'No [finding]' statements with actual findings where abnormalities exist")
        user_parts.append("4. Keep normal findings only where no abnormalities are present")
        user_parts.append("5. Maintain the template's formatting style (bullets, line breaks, etc.)")
        user_parts.append("")
        user_parts.append("Template Structure:")
        user_parts.append("---")
        user_parts.append(rendered_template)
        user_parts.append("---")
        user_parts.append("")
        
        if master_instructions:
            user_parts.append("=== ADDITIONAL INSTRUCTIONS ===")
            user_parts.append(master_instructions)
            user_parts.append("")
        
        user_parts.append("=== KEY PRINCIPLES ===")
        user_parts.append("")
        user_parts.append("1. Use the template structure as a GUIDE - fill it with actual findings from the case")
        user_parts.append("2. Replace normal/example findings in template with actual findings where abnormalities exist")
        user_parts.append("3. Keep template sections that are relevant, remove or modify sections that don't apply")
        user_parts.append("4. Preserve ALL descriptive details from the findings (size, location, characteristics, etc.)")
        user_parts.append("5. Use British English spelling throughout")
        user_parts.append("6. Write in prose format unless template specifies bullets")
        user_parts.append("")
        
        user_parts.append("=== CRITICAL REMINDER ===")
        user_parts.append("")
        user_parts.append("DO NOT return the template text itself.")
        user_parts.append("DO generate a complete radiology report using the template structure.")
        user_parts.append("The template shows you HOW to format and organize your report - it is NOT the report content.")
        user_parts.append("")
        
        user_parts.append("=== GENERATE REPORT NOW ===")
        user_parts.append("")
        user_parts.append("Generate a complete radiology report following the template structure above, using the findings provided.")
        
        user_prompt = "\n".join(user_parts)
        
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }
    
    def build_unified_master_prompt(
        self,
        template: str,
        variable_values: Dict[str, str],
        template_name: Optional[str] = None,
        template_description: Optional[str] = None,
        master_instructions: Optional[str] = None,
        model_name: Optional[str] = None
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
            model_name: Optional model name to use simpler prompt structure (e.g., "zai-glm-4.6")
            
        Returns:
            Dictionary with 'system_prompt' and 'user_prompt' keys
        """
        # Use simpler prompt structure for zai-glm-4.6
        if model_name == "zai-glm-4.6":
            return self._build_simple_prompt_for_zai_glm(
                template, variable_values, template_name, template_description, master_instructions
            )
        
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
        user_parts.append("- Formatting preferences (style, length, bullets, line breaks)")
        user_parts.append("- Regional organization preferences (anatomical order)")
        user_parts.append("- Grouping preferences (how structures should be grouped)")
        user_parts.append("")
        user_parts.append("Analyze the template below and determine:")
        user_parts.append("1. What sections/structure has the user explicitly defined?")
        user_parts.append("2. What content organization guidance has the user provided?")
        user_parts.append("3. What regional organization (if any) does the template specify? (Head → Neck → Thorax → Abdomen/Pelvis, or custom order?)")
        user_parts.append("4. What formatting preferences does the template specify? (line breaks, sentence structure, etc.)")
        user_parts.append("5. What grouping preferences does the template specify? (how structures should be grouped)")
        user_parts.append("6. What aspects are undefined and need standard conventions?")
        user_parts.append("")
        user_parts.append("Synthesis principle:")
        user_parts.append("User's explicit guidance = ABSOLUTE PRIORITY")
        user_parts.append("Undefined elements = Fill with professional radiology standards (enhanced 5 critical rules)")
        user_parts.append("")
        user_parts.append("Plan your report structure synthesis:")
        user_parts.append("- [State your interpretation of the template type and structure]")
        user_parts.append("- [Identify what's explicit vs what needs fallback]")
        user_parts.append("- [Formulate your final section order and content strategy]")
        user_parts.append("- [Determine regional organization: template-specified or standard order?]")
        user_parts.append("- [Determine formatting: template-specified or line-break formatting?]")
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
        user_parts.append("• Prior imaging: Extract modality, date, region (if mentioned in <findings>) - **CRITICAL: Comparison section should ONLY list the previous study reference, NOT what it showed**")
        user_parts.append("• Limitations: Technical factors affecting interpretation (if any)")
        user_parts.append("")
        user_parts.append("For each verified finding:")
        user_parts.append("- Clinical significance: Urgent/significant vs incidental?")
        user_parts.append("- Which anatomical region/system?")
        user_parts.append("- Key differentials?")
        user_parts.append("- Pertinent negatives relevant to these differentials?")
        user_parts.append("- **CRITICAL: Extract ALL descriptive qualifiers** (size, location, characteristics, enhancement patterns, signal characteristics, margins, etc.) - these MUST be preserved in the report")
        user_parts.append("")
        
        # Step 4: Anatomical Scope & Structure Planning
        user_parts.append("**Step 4: Anatomical Scope & Structure Planning**")
        user_parts.append("• List ALL anatomical regions visible on this scan type including scan extremities")
        user_parts.append("• Which structures appear in <findings>? → Report these")
        user_parts.append("• Which structures NOT in <findings>? → Document as normal/unremarkable")
        user_parts.append("")
        user_parts.append("**REGIONAL ORGANIZATION - CRITICAL:**")
        user_parts.append("• **If template specifies regional organization → Follow it exactly**")
        user_parts.append("• **If template is silent → Use standard radiological order:** Head → Neck/C-spine → Thorax → Abdomen/Pelvis")
        user_parts.append("• For multi-region scans (e.g., CT chest/abdomen/pelvis), clearly separate regions with paragraph breaks")
        user_parts.append("• Each major region should start a new paragraph")
        user_parts.append("• Within each region, group related structures logically (pathology first, then normal structures by system)")
        user_parts.append("• **CRITICAL: Abdomen and Pelvis should be grouped together as one region (Abdomen/Pelvis)**")
        user_parts.append("")
        user_parts.append("**Standard Regional Order Examples (apply if template silent):**")
        user_parts.append("• CT head → CT neck → CT chest → CT abdomen/pelvis")
        user_parts.append("• CT chest/abdomen/pelvis: Thorax paragraph → Abdomen/Pelvis paragraph")
        user_parts.append("• Trauma CT: Head → C-spine → Thorax → Abdomen/Pelvis")
        user_parts.append("• MRI brain → MRI spine: Brain paragraph → Spine paragraph")
        user_parts.append("")
        user_parts.append("**Regional Organization Principles:**")
        user_parts.append("• Start with most superior region and work inferiorly")
        user_parts.append("• Use paragraph breaks to clearly separate major anatomical regions")
        user_parts.append("• Within each region: pathology findings first, then systematic review of normal structures")
        user_parts.append("• Do NOT mix findings from different major regions in the same paragraph")
        user_parts.append("• Abdomen and Pelvis are treated as one combined region")
        user_parts.append("")
        user_parts.append("PATHOLOGY PARAGRAPHS (if pathology present):")
        user_parts.append("• Paragraph 1: [pathology name] → ALL descriptive qualifiers from input → immediate complications → pertinent negatives → affected structures")
        user_parts.append("• Paragraph 2: [if additional pathology] → ...")
        user_parts.append("• **CRITICAL: Preserve ALL descriptive details from <findings>** - size measurements, enhancement characteristics, signal patterns, margins, location specifics, etc.")
        user_parts.append("• **CRITICAL: Use 2-3 sentences for complex pathology - do NOT create long sentences with comma-separated lists**")
        user_parts.append("• **Sentence 1: Main finding with size, location, enhancement pattern**")
        user_parts.append("• **Sentence 2: Additional morphological features (necrosis, margins, complications)**")
        user_parts.append("• **Sentence 3: Pertinent negatives (can be short sentence)**")
        user_parts.append("• **CRITICAL: Organize pathology by anatomical region - if pathology spans multiple regions, describe each region's findings separately**")
        user_parts.append("")
        user_parts.append("REMAINING ANATOMY PARAGRAPHS:")
        user_parts.append("• **Organize by major anatomical regions first** (Head → Neck → Thorax → Abdomen/Pelvis) - **unless template specifies different order**")
        user_parts.append("• Within each region: Group 1: [System, e.g., \"biliary system\"] → 1-2 sentences covering liver and gallbladder together")
        user_parts.append("• Within each region: Group 2: [System, e.g., \"other solid organs\"] → 1-2 sentences covering spleen, pancreas, etc.")
        user_parts.append("• Within each region: Group 3: [System, e.g., \"hollow viscera\"] → 1-2 sentences covering bowel, bladder, etc.")
        user_parts.append("• **CRITICAL: Always mention liver and gallbladder together** - they are part of the same biliary system")
        user_parts.append("• Target: Maximum 2-3 sentences per group")
        user_parts.append("• **CRITICAL: Remember to group structures in a logical/coherent fashion - replace normal findings for abnormalities where present and don't duplicate in remaining systematic review**")
        user_parts.append("• **CRITICAL: DO NOT mix unrelated anatomical systems in single sentences - each system should have its own sentence or be grouped only with related systems**")
        user_parts.append("• **CRITICAL: Use paragraph breaks to clearly separate major anatomical regions (Abdomen/Pelvis together as one region)**")
        user_parts.append("")
        user_parts.append("**CRITICAL: Do NOT create one massive list of all normal structures at the end - distribute systematically across logical paragraphs**")
        user_parts.append("**Ensure gastrointestinal tract review**: For abdominal/pelvic imaging, always comment on bowel (calibre, wall thickness, abnormal enhancement, obstruction etc.)")
        user_parts.append("")
        user_parts.append("Apply template structure where specified:")
        user_parts.append("- If template defines section order → Follow it")
        user_parts.append("- If template defines anatomical order → Follow it")
        user_parts.append("- If template defines regional organization → Follow it")
        user_parts.append("- If template defines formatting preferences → Follow it")
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
        user_parts.append("□ **ALL descriptive qualifiers from <findings> preserved?** (size, location, characteristics, enhancement, signal patterns, margins, etc.)")
        user_parts.append("□ **Logical grouping maintained without losing detail?**")
        user_parts.append("□ **Unrelated anatomical systems kept in separate sentences?**")
        user_parts.append("□ **Major anatomical regions clearly separated with paragraph breaks?** (Head → Neck → Thorax → Abdomen/Pelvis)")
        user_parts.append("□ **Regional organization follows standard radiological order?** (Superior to inferior, unless template specifies different order)")
        user_parts.append("□ **Did I avoid duplicating bowel structures?** (If \"bowel loops\" are normal, don't separately mention rectum/sigmoid colon unless there's pathology)")
        user_parts.append("□ **Did I group liver and gallbladder together?** (They are part of the biliary system and should be mentioned together, not separated)")
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
        user_parts.append("❌ BAD: \"Bowel loops are of normal calibre. ... The rectum and sigmoid colon are normal.\"")
        user_parts.append("✅ GOOD: \"Bowel loops are of normal calibre without wall thickening.\"")
        user_parts.append("")
        user_parts.append("**RULE 2: GROUP LOGICALLY, PRESERVE DETAIL**")
        user_parts.append("Combine related normal structures into single sentences. **CRITICAL: When grouping, preserve ALL descriptive qualifiers from <findings> - do NOT strip down complex findings to simple statements.**")
        user_parts.append("")
        user_parts.append("❌ BAD: \"The liver is unremarkable. The gallbladder is unremarkable. The spleen is unremarkable. The pancreas is unremarkable.\"")
        user_parts.append("✅ GOOD: \"The solid abdominal organs are unremarkable.\"")
        user_parts.append("")
        user_parts.append("❌ BAD (over-simplified complex finding): \"There is a liver lesion.\"")
        user_parts.append("✅ GOOD (preserves descriptive qualifiers): \"There is a 4.2 cm heterogeneous liver lesion in segment 7 showing arterial phase enhancement with delayed washout and pseudocapsule formation.\"")
        user_parts.append("")
        user_parts.append("**CRITICAL GROUPING PRINCIPLE:**")
        user_parts.append("- Group structures logically by anatomical system or region")
        user_parts.append("- Replace normal findings with abnormalities where present (don't duplicate)")
        user_parts.append("- Preserve ALL descriptive qualifiers from input findings")
        user_parts.append("- Don't strip down complex pathology to simple statements")
        user_parts.append("- Use multiple sentences if needed to preserve detail")
        user_parts.append("- **DO NOT group unrelated anatomical systems in single sentences** (e.g., bowel + vessels + lymph nodes)")
        user_parts.append("- **DO NOT create comma-separated lists for complex pathology - use multiple focused sentences instead**")
        user_parts.append("- **Organize by major anatomical regions first** (Head → Neck → Thorax → Abdomen/Pelvis, unless template specifies different order)")
        user_parts.append("- **Use paragraph breaks to clearly separate major anatomical regions**")
        user_parts.append("- **Abdomen and Pelvis are grouped together as one region**")
        user_parts.append("")
        user_parts.append("**GROUPING BOUNDARIES - CRITICAL:**")
        user_parts.append("• **Related structures within same system** = Can group together (e.g., \"liver, spleen, pancreas\" = solid organs)")
        user_parts.append("• **Different anatomical systems** = MUST be separate sentences (e.g., bowel ≠ vessels ≠ lymph nodes)")
        user_parts.append("• **Different major anatomical regions** = MUST be separate paragraphs (e.g., thorax ≠ abdomen/pelvis)")
        user_parts.append("• **Examples of systems that should NOT be mixed:**")
        user_parts.append("  - Hollow viscera (bowel, stomach, bladder) ≠ Vascular structures (aorta, IVC, vessels) ≠ Lymphatic system (lymph nodes, fluid)")
        user_parts.append("  - Solid organs (liver, spleen, pancreas) ≠ Hollow viscera ≠ Vascular structures")
        user_parts.append("  - Each system should have its own sentence or grouped with related systems only")
        user_parts.append("• **CRITICAL: Bowel system components are all part of the same system** - bowel loops, small bowel, large bowel, colon, rectum, sigmoid colon, appendix are all hollow viscera/bowel")
        user_parts.append("• **If \"bowel loops\" are already described as normal, do NOT separately mention rectum/sigmoid colon unless there is specific pathology**")
        user_parts.append("• **Bowel loops = general term covering entire bowel system** - if bowel loops are normal, individual bowel segments (rectum, sigmoid colon) should NOT be mentioned separately")
        user_parts.append("• **CRITICAL: Liver and gallbladder are part of the biliary system and should ALWAYS be mentioned together** - when describing liver findings, immediately follow with gallbladder findings in the same sentence or adjacent sentence")
        user_parts.append("• **Do NOT separate liver and gallbladder** - they are anatomically and functionally related (biliary system)")
        user_parts.append("• **Examples of regions that should NOT be mixed:**")
        user_parts.append("  - Head ≠ Neck ≠ Thorax ≠ Abdomen/Pelvis")
        user_parts.append("  - Each major region should have its own paragraph")
        user_parts.append("  - Abdomen and Pelvis are combined as one region")
        user_parts.append("")
        user_parts.append("❌ BAD (mixing unrelated systems): \"Bowel loops are normal; the aorta and IVC are normal; there is no lymphadenopathy or free fluid.\"")
        user_parts.append("✅ GOOD (separate sentences per system): \"Bowel loops are of normal calibre without wall thickening. The abdominal aorta and inferior vena cava are of normal calibre. No lymphadenopathy or free fluid.\"")
        user_parts.append("")
        user_parts.append("❌ BAD (mixing systems): \"The liver, spleen and bowel are unremarkable.\"")
        user_parts.append("✅ GOOD (related systems only): \"The liver and spleen are unremarkable. Bowel loops are of normal calibre.\"")
        user_parts.append("")
        user_parts.append("❌ BAD (mixing regions): \"The liver is unremarkable. The lungs show no nodules. The spleen is normal.\"")
        user_parts.append("✅ GOOD (regional separation): \"THORAX: The lungs and mediastinum are unremarkable.")
        user_parts.append("")
        user_parts.append("ABDOMEN/PELVIS: The liver, spleen and pancreas are unremarkable. The bladder and rectum are normal.\"")
        user_parts.append("")
        user_parts.append("**RULE 3: INTEGRATE PERTINENT NEGATIVES**")
        user_parts.append("Pertinent negatives belong WITH the pathology they relate to, not separately.")
        user_parts.append("")
        user_parts.append("❌ BAD: \"There is a 3 cm liver lesion. No biliary dilatation. No ascites. ... [Later:] The bile ducts are not dilated.\"")
        user_parts.append("✅ GOOD: \"There is a 3 cm liver lesion without biliary dilatation or ascites.\"")
        user_parts.append("")
        user_parts.append("**RULE 4: ADAPTIVE SENTENCE LENGTH**")
        user_parts.append("• Normal anatomy sentences: Maximum 20 words (simple structures)")
        user_parts.append("• Simple pathology sentences: Maximum 30 words")
        user_parts.append("• **Complex pathology sentences: Use 2-3 sentences if needed to preserve ALL descriptive qualifiers** (size, location, enhancement patterns, signal characteristics, margins, etc.)")
        user_parts.append("• **CRITICAL: Do NOT sacrifice descriptive detail for brevity - if a finding has multiple qualifiers in <findings>, preserve them all, even if it requires multiple sentences**")
        user_parts.append("• **CRITICAL: Do NOT create long sentences with comma-separated lists - break complex pathology descriptions into 2-3 focused sentences instead**")
        user_parts.append("")
        user_parts.append("❌ BAD (over-simplified): \"There is a liver lesion with enhancement.\"")
        user_parts.append("❌ BAD (long sentence with comma-separated list): \"The lesion shows central necrosis, irregular margins, capsular retraction, and no biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.\"")
        user_parts.append("✅ GOOD (preserves detail, split into focused sentences): \"There is a 4.2 cm heterogeneous liver lesion in segment 7. It demonstrates arterial phase enhancement with delayed washout and pseudocapsule formation. The lesion shows central low-attenuation areas (~1.5 cm) consistent with necrosis and irregular margins with subtle capsular retraction. No biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.\"")
        user_parts.append("")
        user_parts.append("**SENTENCE STRUCTURE PRINCIPLES:**")
        user_parts.append("• Each sentence should focus on ONE main concept or related group of findings")
        user_parts.append("• Complex pathology: Use multiple sentences (2-3) to describe different aspects (morphology, enhancement, complications, pertinent negatives)")
        user_parts.append("• Pertinent negatives: Can be in a separate short sentence after the main pathology description")
        user_parts.append("• DO NOT create run-on sentences mixing unrelated anatomical systems (e.g., bowel + vessels + lymph nodes in one sentence)")
        user_parts.append("• DO NOT use comma-separated lists for multiple unrelated findings - split into separate sentences")
        user_parts.append("")
        user_parts.append("❌ BAD (run-on sentence mixing unrelated systems): \"Bowel loops are normal; the aorta and IVC are normal; there is no lymphadenopathy or free fluid.\"")
        user_parts.append("✅ GOOD (separate focused sentences): \"Bowel loops are of normal calibre without wall thickening. The abdominal aorta and inferior vena cava are of normal calibre. No lymphadenopathy or free fluid.\"")
        user_parts.append("")
        user_parts.append("❌ BAD (comma-separated list for complex pathology): \"The lesion shows necrosis, irregular margins, capsular retraction, and no biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.\"")
        user_parts.append("✅ GOOD (split into focused sentences): \"The lesion shows central necrosis and irregular margins with subtle capsular retraction. No biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.\"")
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
        user_parts.append("**COMPARISON SECTION - CRITICAL RULES:**")
        user_parts.append("• Format: \"Previous [modality] [region] dated [date].\" OR \"No previous imaging available for comparison.\"")
        user_parts.append("• DO NOT include details about what the previous study showed")
        user_parts.append("• DO NOT describe findings from the previous study")
        user_parts.append("• DO NOT compare current findings to previous findings in the Comparison section")
        user_parts.append("• Comparison details belong in Findings section when describing changes (e.g., \"increased\", \"stable\", \"new\")")
        user_parts.append("")
        user_parts.append("❌ BAD: \"CT head 12/10/2024 showed 15 mm right MCA territory infarct.\"")
        user_parts.append("✅ GOOD: \"CT head dated 12/10/2024.\"")
        user_parts.append("")
        user_parts.append("❌ BAD: \"MRI brain with contrast performed 6 months ago demonstrated multiple periventricular white matter lesions; current study shows a new enhancing occipital lesion.\"")
        user_parts.append("✅ GOOD: \"Previous MRI brain with contrast dated [date].\"")
        user_parts.append("")
        user_parts.append("**STANDARD CONVENTIONS (apply where template is undefined):**")
        user_parts.append("")
        user_parts.append("Section Structure:")
        user_parts.append("• Comparison: Extract from <findings> OR 'No previous imaging available for comparison' - **ONLY list study reference, NOT what it showed**")
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
        user_parts.append("**Example - CT Chest/Abdomen/Pelvis (Regional Organization):**")
        user_parts.append("")
        user_parts.append("**Comparison:**")
        user_parts.append("Previous CT chest/abdomen/pelvis with contrast dated 3 months ago.")
        user_parts.append("")
        user_parts.append("**Findings:**")
        user_parts.append("THORAX:")
        user_parts.append("The lungs are clear with no pulmonary nodules or consolidation.")
        user_parts.append("The mediastinum shows no lymphadenopathy.")
        user_parts.append("The heart and great vessels are unremarkable.")
        user_parts.append("No pleural or pericardial effusion.")
        user_parts.append("")
        user_parts.append("ABDOMEN/PELVIS:")
        user_parts.append("There is a 4.2 cm heterogeneous liver lesion in segment 7 demonstrating arterial phase hyperenhancement with delayed washout and peripheral pseudocapsule formation.")
        user_parts.append("The lesion contains central low-attenuation areas (~1.5 cm) consistent with necrosis and shows irregular margins with subtle capsular retraction.")
        user_parts.append("No biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.")
        user_parts.append("The remainder of the liver parenchyma is unremarkable.")
        user_parts.append("The gallbladder is normal.")
        user_parts.append("The spleen (12 cm craniocaudal), pancreas and adrenal glands are unremarkable.")
        user_parts.append("The kidneys enhance symmetrically without hydronephrosis, calculi or masses.")
        user_parts.append("Bowel loops are of normal calibre without wall thickening or abnormal enhancement.")
        user_parts.append("The abdominal aorta and inferior vena cava are of normal calibre.")
        user_parts.append("No lymphadenopathy or free fluid.")
        user_parts.append("")
        user_parts.append("**Impression:**")
        user_parts.append("Hepatocellular carcinoma in segment 7 with arterial hyperenhancement, delayed washout and pseudocapsule formation. No evidence of thoracic metastatic disease.")
        user_parts.append("")
        user_parts.append("**Note:** This example demonstrates:")
        user_parts.append("- Clear regional separation (THORAX → ABDOMEN/PELVIS)")
        user_parts.append("- Each sentence on its own line within each region")
        user_parts.append("- Liver and gallbladder grouped together (biliary system)")
        user_parts.append("- Complex pathology split into multiple focused sentences")
        user_parts.append("- No duplication of structures")
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
        user_parts.append("**REPORT FORMATTING:**")
        user_parts.append("• **If template specifies formatting preferences → Follow them exactly**")
        user_parts.append("• **If template is silent → Apply standard formatting:**")
        user_parts.append("  - Bold section headers: **Comparison:**, **Limitations:**, **Findings:**, **Impression:**")
        user_parts.append("  - Double line breaks (\\n\\n) between major sections")
        user_parts.append("  - Single line breaks (\\n) between paragraphs within Findings")
        user_parts.append("  - **CRITICAL: Within each major anatomical region (THORAX, ABDOMEN/PELVIS, etc.), place each sentence on its own line for improved readability**")
        user_parts.append("  - **Formatting preference: Each sentence within a region should start on a new line**")
        user_parts.append("• Impression: Prose format (flowing sentences), NOT bullet points (unless template specifies bullets)")
        user_parts.append("• No XML tags, prompt references, or markdown in report content")
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
        
        # Common Mistakes to Avoid
        user_parts.append("**COMMON MISTAKES TO AVOID:**")
        user_parts.append("")
        user_parts.append("❌ **Over-simplification (stripping descriptive qualifiers):**")
        user_parts.append("Input: \"4.2 cm heterogeneous liver lesion in segment 7 with arterial phase enhancement, delayed washout, pseudocapsule formation\"")
        user_parts.append("❌ BAD: \"There is a liver lesion.\"")
        user_parts.append("✅ GOOD: \"There is a 4.2 cm heterogeneous liver lesion in segment 7 demonstrating arterial phase enhancement with delayed washout and pseudocapsule formation.\"")
        user_parts.append("")
        user_parts.append("❌ **Redundancy (same structure mentioned multiple times):**")
        user_parts.append("\"The liver is unremarkable in appearance. The gallbladder is unremarkable. The spleen appears normal. The pancreas is unremarkable in appearance.\"")
        user_parts.append("✅ **Corrected (grouped efficiently):**")
        user_parts.append("\"The liver, gallbladder, spleen, pancreas and adrenal glands are unremarkable.\"")
        user_parts.append("")
        user_parts.append("❌ **Pertinent negatives repeated separately:**")
        user_parts.append("\"There is a 4 cm liver lesion. The bile ducts are not dilated. ... [Later in report:] No biliary dilatation.\"")
        user_parts.append("✅ **Corrected (integrated once):**")
        user_parts.append("\"There is a 4 cm hepatic lesion without biliary dilatation or vascular involvement.\"")
        user_parts.append("")
        user_parts.append("❌ **Long sentences with comma-separated lists (complex pathology):**")
        user_parts.append("\"The lesion shows central necrosis, irregular margins, capsular retraction, and no biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.\"")
        user_parts.append("✅ **Corrected (split into focused sentences):**")
        user_parts.append("\"The lesion shows central low-attenuation areas (~1.5 cm) consistent with necrosis and irregular margins with subtle capsular retraction. No biliary dilatation, vascular invasion, satellite lesions, portal vein thrombosis or ascites.\"")
        user_parts.append("")
        user_parts.append("❌ **Run-on sentences mixing unrelated anatomical systems:**")
        user_parts.append("\"Bowel loops are normal; the aorta and IVC are normal; there is no lymphadenopathy or free fluid.\"")
        user_parts.append("✅ **Corrected (separate focused sentences):**")
        user_parts.append("\"Bowel loops are of normal calibre without wall thickening. The abdominal aorta and inferior vena cava are of normal calibre. No lymphadenopathy or free fluid.\"")
        user_parts.append("")
        user_parts.append("❌ **Mixing major anatomical regions in same paragraph:**")
        user_parts.append("\"The liver is unremarkable. The lungs show no nodules. The spleen is normal.\"")
        user_parts.append("✅ **Corrected (regional separation with paragraph breaks):**")
        user_parts.append("\"THORAX: The lungs and mediastinum are unremarkable.")
        user_parts.append("")
        user_parts.append("ABDOMEN/PELVIS: The liver, spleen and pancreas are unremarkable.\"")
        user_parts.append("")
        user_parts.append("❌ **Comparison section includes details from previous study:**")
        user_parts.append("\"CT head 12/10/2024 showed 15 mm right MCA territory infarct.\"")
        user_parts.append("✅ **Corrected (simple study reference only):**")
        user_parts.append("\"CT head dated 12/10/2024.\"")
        user_parts.append("")
        user_parts.append("❌ **Separating liver and gallbladder (they should be grouped together):**")
        user_parts.append("\"The liver contains multiple small cysts; the remainder of the liver is unremarkable. The spleen, pancreas and adrenal glands are unremarkable. The gallbladder is normal.\"")
        user_parts.append("✅ **Corrected (liver and gallbladder grouped together):**")
        user_parts.append("\"The liver contains multiple small cysts; the remainder of the liver is unremarkable. The gallbladder is normal. The spleen, pancreas and adrenal glands are unremarkable.\"")
        user_parts.append("")
        user_parts.append("❌ **Duplicating bowel structures (bowel loops already covers rectum/sigmoid colon):**")
        user_parts.append("\"Bowel loops are of normal calibre without wall thickening. The rectum and sigmoid colon are normal.\"")
        user_parts.append("✅ **Corrected (bowel loops already covers entire bowel system):**")
        user_parts.append("\"Bowel loops are of normal calibre without wall thickening.\"")
        user_parts.append("")
        user_parts.append("❌ **Verbose impression with redundant explanatory phrases:**")
        user_parts.append("\"No pulmonary metastases or mediastinal lymphadenopathy identified, indicating no evidence of thoracic metastatic disease.\"")
        user_parts.append("✅ **Corrected (direct conclusion, no redundancy):**")
        user_parts.append("\"No evidence of thoracic metastatic disease.\"")
        user_parts.append("")
        
        # Mandatory Self-Check (from gptoss.json)
        user_parts.append("**BEFORE OUTPUTTING - MANDATORY SELF-CHECK:**")
        user_parts.append("")
        user_parts.append("□ Did I mention any anatomical structure more than once? (Re-read and verify)")
        user_parts.append("□ Did I avoid duplicating bowel structures? (If \"bowel loops\" are normal, don't separately mention rectum/sigmoid colon unless there's pathology)")
        user_parts.append("□ Did I group liver and gallbladder together? (They are part of the biliary system and should be mentioned together, not separated)")
        user_parts.append("□ Are all sentences appropriately structured? (Normal anatomy ≤20 words; complex pathology may need 2-3 sentences to preserve detail - avoid comma-separated lists)")
        user_parts.append("□ Did I avoid run-on sentences mixing unrelated anatomical systems? (Each sentence should focus on one main concept or related group)")
        user_parts.append("□ **Did I organize findings by major anatomical regions?** (Head → Neck → Thorax → Abdomen/Pelvis, with clear paragraph breaks - unless template specifies different order)")
        user_parts.append("□ **Did I use paragraph breaks to separate major anatomical regions?** (Each major region should have its own paragraph - Abdomen/Pelvis together as one region)")
        user_parts.append("□ **Did I format each sentence on its own line within each major anatomical region?** (Each sentence within THORAX, ABDOMEN/PELVIS, etc. should be on a separate line for readability - unless template specifies different formatting)")
        user_parts.append("□ Is my Comparison section simple? (Only lists previous study reference - modality, date, region - no details about what it showed)")
        user_parts.append("□ Is my impression diagnostic conclusions only? (No descriptive details from Findings, no benign incidentals below threshold, no redundant explanatory phrases like \"indicating\" or \"demonstrating\")")
        user_parts.append("□ Did I group related normal structures together? (Not listed individually)")
        user_parts.append("□ Are pertinent negatives integrated WITH pathology? (Not repeated separately)")
        user_parts.append("□ **Did I preserve ALL descriptive qualifiers from <findings>?** (size, location, enhancement patterns, signal characteristics, margins, etc.)")
        user_parts.append("□ **Did I group logically without losing detail?** (Complex findings should remain detailed, not stripped down)")
        user_parts.append("□ **Did I use multiple sentences for complex pathology instead of comma-separated lists?** (Complex findings should be split into 2-3 focused sentences)")
        user_parts.append("□ Did I respect the template structure where specified?")
        user_parts.append("□ Did I apply the enhanced 5 critical rules where template was silent?")
        user_parts.append("")
        user_parts.append("If you found ANY issues in this self-check, FIX THEM NOW before outputting JSON.")
        user_parts.append("")
        user_parts.append("=== GENERATE REPORT NOW ===")
        
        user_prompt = "\n".join(user_parts)
        
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }
