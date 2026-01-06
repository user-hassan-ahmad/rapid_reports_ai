import { writable, derived, get } from 'svelte/store';
import { token } from './auth';
import { API_URL } from '$lib/config';
import { logger } from '$lib/utils/logger';

// Tags store - holds all unique tags with loading and error states
const tagsData = writable({
	tags: [],
	loading: false,
	error: null
});

let isLoadingTags = false; // Guard against concurrent loads

// Create a custom store with methods
function createTagsStore() {
	return {
		subscribe: tagsData.subscribe,
		
		// Load all unique tags from API
		async loadTags() {
			// Prevent concurrent loads
			if (isLoadingTags) return;
			isLoadingTags = true;
			
			tagsData.update(state => ({ ...state, loading: true, error: null }));
			try {
				const headers = { 'Content-Type': 'application/json' };
				const currentToken = get(token);
				if (currentToken) {
					headers['Authorization'] = `Bearer ${currentToken}`;
				}
				
				const response = await fetch(`${API_URL}/api/templates/tags`, {
					headers
				});
				
				if (response.ok) {
					const data = await response.json();
					if (data.success) {
						tagsData.set({ tags: data.tags || [], loading: false, error: null });
					} else {
						tagsData.set({ tags: [], loading: false, error: data.error || 'Failed to load tags' });
					}
				} else {
					tagsData.set({ tags: [], loading: false, error: 'Failed to load tags' });
				}
			} catch (err) {
				logger.error('Failed to load tags:', err);
				tagsData.set({ tags: [], loading: false, error: 'Failed to load tags' });
			} finally {
				isLoadingTags = false;
			}
		},
		
		// Force refresh from API
		async refreshTags() {
			await this.loadTags();
		},
		
		// Get current tags (for non-reactive access)
		getTags() {
			return get(tagsData).tags;
		},
		
		// Get tags array directly (reactive)
		get tags() {
			return get(tagsData).tags;
		}
	};
}

export const tagsStore = createTagsStore();

