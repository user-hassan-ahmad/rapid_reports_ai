/**
 * The dictation package (plan 2026-09-29-dictation-v2-release): what the lab found, the default
 * dictation on the normal Quick Reports tab wherever the server allows it (RR_DICTATION_V2=1,
 * reported by /api/settings/status as `dictation_v2`: the kill switch). A browser opts out with
 * localStorage `rr_dictation_v2=0`. The scratchpad then runs exactly what the last lab sessions
 * ran, and the backend enables its side per connection (`v2=1`). The lab page keeps its own config.
 */
import type { LabConfig } from './types';

export const DICTATION_V2_KEY = 'rr_dictation_v2';

export const PACKAGE_CONFIG: LabConfig = {
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

/** On unless this browser opted out ("0"). */
export function dictationV2On(store: Storage | undefined = storage()): boolean {
	try {
		return store?.getItem(DICTATION_V2_KEY) !== '0';
	} catch {
		return true;
	}
}

/** The lab page's config wins; else the package where the server allows it and the browser has
 *  not opted out; else null (today's production dictation). */
export function effectiveConfig(
	lab: LabConfig | null,
	store: Storage | undefined = storage(),
	serverAllows = false
): LabConfig | null {
	return lab ?? (serverAllows && dictationV2On(store) ? PACKAGE_CONFIG : null);
}
