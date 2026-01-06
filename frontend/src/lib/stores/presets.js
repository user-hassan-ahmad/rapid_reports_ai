import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { API_URL } from '$lib/config';
import { token } from './auth';
import { get } from 'svelte/store';

// Custom presets store
export const customPresets = writable({
	findings: [],
	impression: []
});

// Loading state
export const presetsLoading = writable(false);

// Load from localStorage on init
if (browser) {
	const cached = localStorage.getItem('customPresets');
	if (cached) {
		try {
			customPresets.set(JSON.parse(cached));
		} catch (e) {
			console.error('Failed to parse cached presets:', e);
		}
	}
}

// Persist to localStorage when store changes
customPresets.subscribe(value => {
	if (browser) {
		localStorage.setItem('customPresets', JSON.stringify(value));
	}
});

export async function fetchCustomPresets(sectionType = null) {
	presetsLoading.set(true);
	try {
		const authToken = get(token);
		if (!authToken) {
			presetsLoading.set(false);
			return;
		}

		const url = sectionType 
			? `${API_URL}/api/writing-style-presets?section_type=${sectionType}`
			: `${API_URL}/api/writing-style-presets`;
		
		const res = await fetch(url, {
			headers: { 'Authorization': `Bearer ${authToken}` }
		});
		
		if (res.ok) {
			const data = await res.json();
			if (data.success) {
				// Group by section type
				const grouped = { findings: [], impression: [] };
				data.presets.forEach(p => {
					grouped[p.section_type].push(p);
				});
				customPresets.set(grouped);
			}
		}
	} catch (err) {
		console.error('Failed to fetch presets:', err);
	} finally {
		presetsLoading.set(false);
	}
}

export async function savePreset(name, settings, sectionType = 'findings', icon = '⭐', description = null) {
	try {
		const authToken = get(token);
		if (!authToken) {
			return { success: false, error: 'Not authenticated' };
		}

		const res = await fetch(`${API_URL}/api/writing-style-presets`, {
			method: 'POST',
			headers: {
				'Authorization': `Bearer ${authToken}`,
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({ name, settings, section_type: sectionType, icon, description })
		});
		
		if (res.ok) {
			const data = await res.json();
			if (data.success) {
				// Update local store
				customPresets.update(state => {
					state[sectionType].push(data.preset);
					return state;
				});
				return { success: true, preset: data.preset };
			}
		} else if (res.status === 400) {
			const errorData = await res.json();
			return { success: false, error: errorData.detail || 'Preset name already exists' };
		}
		return { success: false, error: 'Failed to save preset' };
	} catch (err) {
		console.error('Failed to save preset:', err);
		return { success: false, error: 'Network error' };
	}
}

export async function updatePreset(presetId, updates) {
	try {
		const authToken = get(token);
		if (!authToken) {
			return { success: false, error: 'Not authenticated' };
		}

		const res = await fetch(`${API_URL}/api/writing-style-presets/${presetId}`, {
			method: 'PUT',
			headers: {
				'Authorization': `Bearer ${authToken}`,
				'Content-Type': 'application/json'
			},
			body: JSON.stringify(updates)
		});
		
		if (res.ok) {
			const data = await res.json();
			if (data.success) {
				// Update local store
				customPresets.update(state => {
					const section = data.preset.section_type;
					const idx = state[section].findIndex(p => p.id === presetId);
					if (idx !== -1) {
						state[section][idx] = data.preset;
					}
					return state;
				});
				return { success: true, preset: data.preset };
			}
		} else if (res.status === 404) {
			return { success: false, error: 'Preset not found' };
		}
		return { success: false, error: 'Failed to update preset' };
	} catch (err) {
		console.error('Failed to update preset:', err);
		return { success: false, error: 'Network error' };
	}
}

export async function deletePreset(presetId, sectionType) {
	try {
		const authToken = get(token);
		if (!authToken) {
			return { success: false, error: 'Not authenticated' };
		}

		const res = await fetch(`${API_URL}/api/writing-style-presets/${presetId}`, {
			method: 'DELETE',
			headers: { 'Authorization': `Bearer ${authToken}` }
		});
		
		if (res.ok) {
			const data = await res.json();
			if (data.success) {
				// Update local store
				customPresets.update(state => {
					state[sectionType] = state[sectionType].filter(p => p.id !== presetId);
					return state;
				});
				return { success: true };
			}
		} else if (res.status === 404) {
			return { success: false, error: 'Preset not found' };
		}
		return { success: false, error: 'Failed to delete preset' };
	} catch (err) {
		console.error('Failed to delete preset:', err);
		return { success: false, error: 'Network error' };
	}
}

export async function trackPresetUsage(presetId) {
	try {
		const authToken = get(token);
		if (!authToken) return;

		await fetch(`${API_URL}/api/writing-style-presets/${presetId}/use`, {
			method: 'POST',
			headers: { 'Authorization': `Bearer ${authToken}` }
		});
	} catch (err) {
		// Silent fail - usage tracking is non-critical
		console.debug('Failed to track preset usage:', err);
	}
}

