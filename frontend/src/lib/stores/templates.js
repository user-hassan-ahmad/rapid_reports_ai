import { writable, derived, get } from 'svelte/store';
import { token } from './auth';
import { API_URL } from '$lib/config';
import { logger } from '$lib/utils/logger';

// Templates store - holds all templates with loading and error states
const templatesData = writable({
	templates: [],
	loading: false,
	error: null
});

// Store for selected template ID
export const selectedTemplateId = writable(null);

// Derived store that automatically syncs selectedTemplate with templates array
// This ensures selectedTemplate always has the latest data from templates array
export const selectedTemplate = derived(
	[templatesData, selectedTemplateId],
	([$templatesData, $selectedTemplateId]) => {
		if (!$selectedTemplateId || !$templatesData.templates || $templatesData.templates.length === 0) {
			return null;
		}
		return $templatesData.templates.find(t => t.id === $selectedTemplateId) || null;
	}
);

let isLoadingTemplates = false; // Guard against concurrent loads

// Create a custom store with methods
function createTemplatesStore() {
	return {
		subscribe: templatesData.subscribe,
		
		// Load all templates from API
		async loadTemplates() {
			// Prevent concurrent loads
			if (isLoadingTemplates) return;
			isLoadingTemplates = true;
			
			templatesData.update(state => ({ ...state, loading: true, error: null }));
			try {
				const headers = { 'Content-Type': 'application/json' };
				const currentToken = get(token);
				if (currentToken) {
					headers['Authorization'] = `Bearer ${currentToken}`;
				}
				
				const response = await fetch(`${API_URL}/api/templates`, {
					headers
				});
				
				if (response.ok) {
					const data = await response.json();
					if (data.success) {
						templatesData.set({ templates: data.templates || [], loading: false, error: null });
					} else {
						templatesData.set({ templates: [], loading: false, error: data.error || 'Failed to load templates' });
					}
				} else {
					templatesData.set({ templates: [], loading: false, error: 'Failed to load templates' });
				}
			} catch (err) {
				logger.error('Failed to load templates:', err);
				templatesData.set({ templates: [], loading: false, error: 'Failed to load templates' });
			} finally {
				isLoadingTemplates = false;
			}
		},
		
		// Add a new template to the store
		addTemplate(template) {
			templatesData.update(state => ({
				...state,
				templates: [...state.templates, template]
			}));
		},
		
		// Update an existing template in the store
		updateTemplate(templateId, updates) {
			templatesData.update(state => ({
				...state,
				templates: state.templates.map(template => 
					template.id === templateId ? { ...template, ...updates } : template
				)
			}));
		},
		
		// Delete a template from the store
		deleteTemplate(templateId) {
			templatesData.update(state => ({
				...state,
				templates: state.templates.filter(template => template.id !== templateId)
			}));
		},
		
		// Force refresh from API
		async refreshTemplates() {
			await this.loadTemplates();
		},
		
		// Get current templates (for non-reactive access)
		getTemplates() {
			return get(templatesData).templates;
		}
	};
}

export const templatesStore = createTemplatesStore();
