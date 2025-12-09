import { writable } from 'svelte/store';
import { get } from 'svelte/store';
import { token } from './auth';
import { API_URL } from '$lib/config';

// Settings store - holds user settings with loading and error states
const settingsData = writable({
	settings: null,
	loading: false,
	error: null
});

let isLoadingSettings = false; // Guard against concurrent loads
let isUpdatingSettings = false; // Guard against concurrent updates

// Create a custom store with methods
function createSettingsStore() {
	return {
		subscribe: settingsData.subscribe,
		
		// Load settings from API
		async loadSettings() {
			// Prevent concurrent loads
			if (isLoadingSettings) return;
			isLoadingSettings = true;
			
			settingsData.update(state => ({ ...state, loading: true, error: null }));
			try {
				const headers = { 'Content-Type': 'application/json' };
				const currentToken = get(token);
				if (currentToken) {
					headers['Authorization'] = `Bearer ${currentToken}`;
				}
				
				const response = await fetch(`${API_URL}/api/settings`, {
					headers
				});
				
				if (response.ok) {
					const data = await response.json();
					if (data.success) {
						settingsData.set({ settings: data, loading: false, error: null });
					} else {
						settingsData.set({ settings: null, loading: false, error: data.error || 'Failed to load settings' });
					}
				} else {
					settingsData.set({ settings: null, loading: false, error: 'Failed to load settings' });
				}
			} catch (err) {
				logger.error('Failed to load settings:', err);
				settingsData.set({ settings: null, loading: false, error: 'Failed to load settings' });
			} finally {
				isLoadingSettings = false;
			}
		},
		
		// Update settings in store and API
		async updateSettings(updates) {
			// Prevent concurrent updates
			if (isUpdatingSettings) return { success: false, error: 'Update in progress' };
			isUpdatingSettings = true;
			
			settingsData.update(state => ({ ...state, loading: true, error: null }));
			try {
				const headers = { 'Content-Type': 'application/json' };
				const currentToken = get(token);
				if (currentToken) {
					headers['Authorization'] = `Bearer ${currentToken}`;
				}
				
				// Get current settings to merge
				const currentData = get(settingsData);
				const currentSettings = currentData.settings || {};
				const mergedSettings = { ...currentSettings, ...updates };
				
				const response = await fetch(`${API_URL}/api/settings`, {
					method: 'POST',
					headers,
					body: JSON.stringify(mergedSettings)
				});
				
				if (response.ok) {
					const data = await response.json();
					if (data.success) {
						// Update store with merged settings
						settingsData.set({ settings: { ...currentSettings, ...updates }, loading: false, error: null });
						return { success: true };
					} else {
						settingsData.update(state => ({ ...state, loading: false, error: data.error || 'Failed to update settings' }));
						return { success: false, error: data.error };
					}
				} else {
					const errorData = await response.json().catch(() => ({}));
					settingsData.update(state => ({ ...state, loading: false, error: errorData.error || 'Failed to update settings' }));
					return { success: false, error: errorData.error || 'Failed to update settings' };
				}
			} catch (err) {
				logger.error('Failed to update settings:', err);
				settingsData.update(state => ({ ...state, loading: false, error: 'Failed to update settings' }));
				return { success: false, error: 'Failed to update settings' };
			} finally {
				isUpdatingSettings = false;
			}
		},
		
		// Force refresh from API
		async refreshSettings() {
			await this.loadSettings();
		},
		
		// Get current settings (for non-reactive access)
		getSettings() {
			return get(settingsData).settings;
		}
	};
}

export const settingsStore = createSettingsStore();
