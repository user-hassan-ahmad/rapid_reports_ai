/**
 * The dictation package (plan 2026-09-29-dictation-v2-release): what the lab found, shipped on
 * the normal Quick Reports tab behind a per-browser flag, `rr_dictation_v2` (localStorage, like
 * `rr_discretionary`). With it on, the scratchpad runs exactly what the last lab sessions ran;
 * the backend enables its side per connection (`v2=1`, allowed by RR_DICTATION_V2). Off:
 * production dictation as before. The lab page keeps its own config.
 */
import type { LabConfig } from './types';

export const DICTATION_V2_KEY = 'rr_dictation_v2';

export const PACKAGE_CONFIG: LabConfig = {
	strategy: 'shadow', // not used by decision-first
	threshold: 0.9,
	showBoth: false, // no comparison candidates on /process
	coverageDebug: false, // no second coverage candidate on /review
	pillThresholds: { hi: 0.8, lo: 0.4 },
	frontDoor: 'decision',
	polish: 'race'
};

function storage(): Storage | undefined {
	try {
		return typeof localStorage !== 'undefined' ? localStorage : undefined;
	} catch {
		return undefined;
	}
}

export function dictationV2On(store: Storage | undefined = storage()): boolean {
	try {
		return store?.getItem(DICTATION_V2_KEY) === '1';
	} catch {
		return false;
	}
}

/** The lab page's config wins; else the package when the flag is on; else null (production). */
export function effectiveConfig(lab: LabConfig | null, store: Storage | undefined = storage()): LabConfig | null {
	return lab ?? (dictationV2On(store) ? PACKAGE_CONFIG : null);
}
