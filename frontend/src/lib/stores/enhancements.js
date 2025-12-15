import { writable } from 'svelte/store';

/**
 * Store for enhancement sidebar state
 * Tracks guidelines count, loading state, and errors
 */
function createEnhancementStore() {
	const { subscribe, set, update } = writable({
		guidelinesCount: 0,
		isLoading: false,
		hasError: false,
		reportId: null
	});

	return {
		subscribe,
		setGuidelinesCount: (count) => update(state => ({ ...state, guidelinesCount: count })),
		setLoading: (loading) => update(state => ({ ...state, isLoading: loading })),
		setError: (hasError) => update(state => ({ ...state, hasError })),
		setReportId: (reportId) => update(state => ({ ...state, reportId })),
		reset: () => set({
			guidelinesCount: 0,
			isLoading: false,
			hasError: false,
			reportId: null
		})
	};
}

export const enhancementStore = createEnhancementStore();


