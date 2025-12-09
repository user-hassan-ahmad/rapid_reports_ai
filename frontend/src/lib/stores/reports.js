import { writable } from 'svelte/store';
import { get } from 'svelte/store';
import { token } from './auth';
import { API_URL } from '$lib/config';
import { logger } from '$lib/utils/logger';

// Reports store - holds all reports with loading and error states
const reportsData = writable({
	reports: [],
	loading: false,
	error: null
});

let isLoadingReports = false; // Guard against concurrent loads

// Create a custom store with methods
function createReportsStore() {
	return {
		subscribe: reportsData.subscribe,
		
		// Load all reports from API
		async loadReports() {
			// Prevent concurrent loads
			if (isLoadingReports) return;
			isLoadingReports = true;
			
			reportsData.update(state => ({ ...state, loading: true, error: null }));
			try {
				const headers = { 'Content-Type': 'application/json' };
				const currentToken = get(token);
				if (currentToken) {
					headers['Authorization'] = `Bearer ${currentToken}`;
				}
				
				const response = await fetch(`${API_URL}/api/reports`, {
					headers
				});
				
				if (response.ok) {
					const data = await response.json();
					if (data.success) {
						reportsData.set({ reports: data.reports || [], loading: false, error: null });
					} else {
						reportsData.set({ reports: [], loading: false, error: data.error || 'Failed to load reports' });
					}
				} else {
					reportsData.set({ reports: [], loading: false, error: 'Failed to load reports' });
				}
			} catch (err) {
				logger.error('Failed to load reports:', err);
				reportsData.set({ reports: [], loading: false, error: 'Failed to load reports' });
			} finally {
				isLoadingReports = false;
			}
		},
		
		// Add a new report to the store
		addReport(report) {
			reportsData.update(state => ({
				...state,
				reports: [report, ...state.reports]
			}));
		},
		
		// Update an existing report in the store
		updateReport(reportId, updates) {
			reportsData.update(state => ({
				...state,
				reports: state.reports.map(report => 
					report.id === reportId ? { ...report, ...updates } : report
				)
			}));
		},
		
		// Delete a report from the store
		deleteReport(reportId) {
			reportsData.update(state => ({
				...state,
				reports: state.reports.filter(report => report.id !== reportId)
			}));
		},
		
		// Delete multiple reports from the store
		deleteReports(reportIds) {
			reportsData.update(state => {
				const idsSet = new Set(reportIds);
				return {
					...state,
					reports: state.reports.filter(report => !idsSet.has(report.id))
				};
			});
		},
		
		// Force refresh from API
		async refreshReports() {
			await this.loadReports();
		},
		
		// Get current reports (for non-reactive access)
		getReports() {
			return get(reportsData).reports;
		}
	};
}

export const reportsStore = createReportsStore();

