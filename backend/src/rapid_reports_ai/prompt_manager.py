"""
Prompt Manager for Radiology Reports AI
Loads and manages prompts for different use cases and models
"""
import os
import json
from typing import Dict, Optional
from pathlib import Path


class PromptManager:
    """Manages prompts for different use cases and models"""
    
    def __init__(self, prompts_dir: str = None):
        """Initialize the prompt manager
        
        Args:
            prompts_dir: Directory containing prompt files. If None, uses default prompts/ dir
        """
        if prompts_dir is None:
            # Get the directory of this file
            base_dir = Path(__file__).parent
            prompts_dir = base_dir / "prompts"
        
        self.prompts_dir = Path(prompts_dir)
        self._prompts_cache = {}
    
    def load_prompt(self, use_case: str, model: str = "default", primary_model: str = None) -> Dict[str, str]:
        """
        Load a prompt for a specific use case and model
        
        Args:
            use_case: The use case (e.g., "radiology_report", "findings_summary")
            model: The model name ("claude", "qwen", or "default")
            primary_model: Optional primary model identifier (e.g., "gpt-oss-120b") for auto template selection
        
        Returns:
            Dictionary with template, description, and variables
        """
        try:
            # New structure: prompts/{use_case}/ directory
            use_case_dir = self.prompts_dir / use_case
            
            # Load metadata
            metadata_file = use_case_dir / "metadata.json"
            if not metadata_file.exists():
                raise FileNotFoundError(f"Metadata not found for use case: {use_case}")
            
            metadata = self._load_json(metadata_file)
            
            # Load template - check primary_model first for auto template selection
            # If primary_model is "claude-sonnet-4-20250514", use claude.json
            # If primary_model is "gpt-oss-120b", use gptoss.json
            # If primary_model is "zai-glm-4.6", use zai-glm-4.6.json
            # Otherwise fallback to unified.json
            template_file = None
            
            if primary_model == "claude-sonnet-4-20250514":
                # Check for claude.json first when primary model is claude-sonnet-4-20250514
                claude_file = use_case_dir / "claude.json"
                if claude_file.exists():
                    template_file = claude_file
                    print(f"load_prompt: Using claude.json for primary model {primary_model}")
            elif primary_model == "gpt-oss-120b":
                # Check for gptoss.json first when primary model is gpt-oss-120b
                gptoss_file = use_case_dir / "gptoss.json"
                if gptoss_file.exists():
                    template_file = gptoss_file
                    print(f"load_prompt: Using gptoss.json for primary model {primary_model}")
            elif primary_model == "zai-glm-4.6":
                # Check for zai-glm-4.6.json first when primary model is zai-glm-4.6
                zai_glm_file = use_case_dir / "zai-glm-4.6.json"
                if zai_glm_file.exists():
                    template_file = zai_glm_file
                    print(f"load_prompt: Using zai-glm-4.6.json for primary model {primary_model}")
            
            # Fallback to unified.json if specific model file not found or primary_model not matched
            if template_file is None:
                unified_file = use_case_dir / "unified.json"
                if unified_file.exists():
                    template_file = unified_file
                elif model != "default":
                    template_file = use_case_dir / f"{model}.json"
                else:
                    # Try default model (claude) if no specific model requested
                    template_file = use_case_dir / "claude.json"
            
            if not template_file.exists():
                raise FileNotFoundError(f"Template not found for {use_case} with model {model}")
            
            template_data = self._load_json(template_file)
            
            # Merge metadata + template
            return {
                **metadata,
                **template_data
            }
        
        except Exception as e:
            raise ValueError(f"Failed to load prompt for {use_case}: {str(e)}")
    
    def _load_json(self, filepath: Path) -> Dict:
        """Load and cache JSON prompt file"""
        if filepath not in self._prompts_cache:
            with open(filepath, 'r') as f:
                self._prompts_cache[filepath] = json.load(f)
        return self._prompts_cache[filepath]
    
    def extract_variables(self, template: str) -> list:
        """
        Extract variable names from a template string
        Looks for {{VARIABLE_NAME}} pattern
        
        Args:
            template: The template string
        
        Returns:
            List of variable names found in the template
        """
        import re
        # Find all {{VARIABLE_NAME}} patterns
        pattern = r'\{\{(\w+)\}\}'
        variables = re.findall(pattern, template)
        return list(set(variables))  # Remove duplicates
    
    def render_prompt(self, prompt: Dict, variables: Dict[str, str] = None) -> str:
        """
        Render a prompt template with variables
        
        Args:
            prompt: The prompt dictionary from load_prompt
            variables: Variables to substitute in the template
        
        Returns:
            Rendered prompt string
        """
        if variables is None:
            variables = {}
        
        template = prompt.get('template', '')
        
        # Replace {{variable_name}} with actual values
        try:
            for var_name, var_value in variables.items():
                template = template.replace(f'{{{{{var_name}}}}}', var_value)
            return template
        except KeyError as e:
            raise ValueError(f"Missing variable in prompt template: {e}")
    
    def get_available_use_cases(self, model: str = None) -> list:
        """Get list of all available use cases, optionally filtered by model
        
        Args:
            model: Optional model name to filter compatible use cases
        
        Returns:
            List of available use cases
        """
        if not self.prompts_dir.exists():
            return []
        
        use_cases = []
        
        # Scan directories in prompts folder
        for use_case_dir in self.prompts_dir.iterdir():
            if not use_case_dir.is_dir():
                continue
            
            use_case_name = use_case_dir.name
            
            # Check if this use case has the requested model
            if model:
                # Check if model-specific file exists
                model_file = use_case_dir / f"{model}.json"
                if not model_file.exists():
                    continue
            
            # Check if metadata exists
            metadata_file = use_case_dir / "metadata.json"
            if not metadata_file.exists():
                continue
            
            try:
                metadata = self._load_json(metadata_file)
                
                # Optionally filter by models field if it exists
                supported_models = metadata.get('models', [])
                if model and supported_models:
                    if model not in supported_models:
                        continue
                
                use_cases.append(use_case_name)
                
            except Exception:
                # If we can't load metadata, skip this use case
                continue
        
        return sorted(use_cases)
    
    def get_use_case_description(self, use_case: str) -> str:
        """Get description for a use case"""
        prompt = self.load_prompt(use_case)
        return prompt.get('description', use_case)
    
    def get_prompt_details(self, use_case: str, model: str = "default") -> Dict:
        """
        Get detailed information about a prompt including its variables
        
        Args:
            use_case: The use case name
            model: The model name
        
        Returns:
            Dictionary with description, template, and variables
        """
        prompt = self.load_prompt(use_case, model)
        
        # Get variables from the prompt if specified
        variables = prompt.get('variables', [])
        
        # If not specified, extract from template
        if not variables:
            template = prompt.get('template', '')
            variables = self.extract_variables(template)
        
        return {
            "description": prompt.get('description', use_case),
            "variables": variables,
            "use_case": use_case
        }


# Global instance
_prompt_manager = None


def get_prompt_manager() -> PromptManager:
    """Get or create the global PromptManager instance"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

