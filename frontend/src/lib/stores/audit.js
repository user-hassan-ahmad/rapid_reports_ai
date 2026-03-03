/**
 * Audit Store - Manages audit/QA state for radiology reports
 * 
 * States:
 * - idle: No audit has been run
 * - loading: Audit is in progress
 * - complete: Audit completed successfully
 * - stale: Report has unsaved changes since last audit
 * - error: Audit failed
 */

import { writable, derived } from 'svelte/store';

function createAuditStore() {
  const { subscribe, set, update } = writable({
    status: 'idle',          // 'idle' | 'loading' | 'complete' | 'stale' | 'error'
    result: null,            // AuditResult object from backend
    auditId: null,           // DB UUID string
    error: null,             // Error message if status is 'error'
    activeCriterion: null,   // Currently highlighted criterion (for hover → scroll)
  });

  return {
    subscribe,

    /**
     * Set loading state when starting an audit
     */
    setLoading: () => update(s => ({ 
      ...s, 
      status: 'loading', 
      error: null 
    })),

    /**
     * Set result after successful audit
     * @param {Object} result - AuditResult from backend
     * @param {string} auditId - Database UUID for the audit
     */
    setResult: (result, auditId) => update(s => ({ 
      ...s, 
      status: 'complete', 
      result, 
      auditId, 
      error: null 
    })),

    /**
     * Mark audit as stale (report has unsaved changes)
     * Only transitions from 'complete' state
     */
    setStale: () => update(s => 
      s.status === 'complete' ? { ...s, status: 'stale' } : s
    ),

    /**
     * Set the active criterion (for hover → scroll interaction)
     * @param {string|null} criterion - Criterion name or null to clear
     */
    setActiveCriterion: (criterion) => update(s => ({ 
      ...s, 
      activeCriterion: criterion 
    })),

    /**
     * Optimistically mark a criterion as acknowledged locally
     * @param {string} criterion - Criterion name to acknowledge
     */
    acknowledgeLocal: (criterion) => update(s => {
      if (!s.result) return s;
      const criteria = s.result.criteria.map(c =>
        c.criterion === criterion ? { ...c, acknowledged: true } : c
      );
      return { ...s, result: { ...s.result, criteria } };
    }),

    /**
     * Set error state
     * @param {string} error - Error message
     */
    setError: (error) => update(s => ({ 
      ...s, 
      status: 'error', 
      error 
    })),

    /**
     * Reset store to initial state
     */
    reset: () => set({ 
      status: 'idle', 
      result: null, 
      auditId: null, 
      error: null, 
      activeCriterion: null 
    }),
  };
}

export const auditStore = createAuditStore();

/**
 * Derived store: Count of unacknowledged flags/warnings
 */
export const unacknowledgedCount = derived(auditStore, $audit => {
  if (!$audit.result?.criteria) return 0;
  return $audit.result.criteria.filter(
    c => (c.status === 'flag' || c.status === 'warning') && !c.acknowledged
  ).length;
});

/**
 * Derived store: Whether all flagged criteria have been acknowledged
 */
export const allAcknowledged = derived(auditStore, $audit => {
  if (!$audit.result?.criteria) return false;
  const flagged = $audit.result.criteria.filter(
    c => c.status === 'flag' || c.status === 'warning'
  );
  return flagged.length > 0 && flagged.every(c => c.acknowledged);
});
