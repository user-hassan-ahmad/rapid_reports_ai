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
        master_instructions: Optional[str] = None,
        model: str = "claude"
    ) -> Dict[str, str]:
        """
        Build system and user prompts following best practices.
        Model-agnostic implementation - works for all models.
        
        Args:
            template: The template content with variables
            variable_values: The values for each variable
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
        system_parts.append("OUTPUT FORMAT: You must provide structured JSON with two fields:")
        system_parts.append("- \"report_content\": The complete radiology report text WITH PROPER FORMATTING (use line breaks between sections, maintain paragraph structure)")
        system_parts.append("- \"description\": A brief 5-15 word summary of key findings for the history tab, max 150 characters (e.g., 'resolving subdural haematoma, no new abnormality' - do NOT repeat the scan type)")
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
        
        # Add master instructions if provided (task-specific customization)
        if master_instructions:
            user_parts.append("=== ADDITIONAL INSTRUCTIONS ===")
            user_parts.append(master_instructions)
            user_parts.append("")
        
        # Add the template structure (task-specific)
        user_parts.append("=== TEMPLATE STRUCTURE ===")
        user_parts.append(rendered_template)
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
        user_parts.append("- Before including ANY finding, verify it is compatible with the scan protocol/type")
        user_parts.append("- Do NOT report findings requiring imaging techniques not performed (e.g., contrast enhancement on non-contrast scans, DWI characteristics on non-DWI sequences, perfusion parameters on non-perfusion scans)")
        user_parts.append("- Cross-check each finding: \"Can this be evaluated with this scan type/protocol?\" If no, exclude it")
        user_parts.append("")
        user_parts.append("Findings Section Writing Style:")
        user_parts.append("- Start directly with anatomical structures — do NOT use introductory statements that repeat the scan modality")
        user_parts.append("- AVOID: 'The CT demonstrates...', 'On this scan...', 'The abdominal CT shows...', 'This examination reveals...'")
        user_parts.append("- USE: Direct anatomical statements: 'The liver...', 'There is...', 'No...', 'Multiple...', etc.")
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
        
        # Add formatting guidance (task-specific)
        user_parts.append("")
        user_parts.append("=== FORMATTING GUIDANCE ===")
        user_parts.append("Adapt formatting to template requirements. General guidance:")
        user_parts.append("- Double line breaks (\\n\\n) between major sections unless template specifies otherwise")
        user_parts.append("- Single line breaks (\\n) between paragraphs within sections")
        user_parts.append("- Proper spacing with lists and bullet points")
        user_parts.append("- Double line break (\\n\\n) before signature block")
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
        user_parts.append("Unless the template specifies otherwise, keep summary brief (2-4 bullets maximum). Prioritize:")
        user_parts.append("1. Findings addressing the clinical question")
        user_parts.append("2. Significant pathology requiring action or follow-up")
        user_parts.append("3. Group ONLY significant incidentals that may require clinical attention into single summary bullet")
        user_parts.append("Focus on clinical impact, not comprehensive listing")
        
        # Add signature requirement
        user_parts.append("")
        user_parts.append("End your report with: {{SIGNATURE}}")
        user_parts.append("")
        user_parts.append("Generate the report now:")
        
        user_prompt = "\n".join(user_parts)
        
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }

