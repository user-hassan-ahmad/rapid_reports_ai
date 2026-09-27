import { writable } from 'svelte/store';
import type { FrontDoor, LabConfig, LabRequestFields, Strategy } from './types';

export const LAB_CONFIG_KEY = 'rr_lab_config';
export const DEFAULT_LAB_CONFIG: LabConfig = {
	strategy: 'shadow',
	threshold: 0.9,
	showBoth: true,
	coverageDebug: true,
	pillThresholds: { hi: 0.8, lo: 0.4 },
	frontDoor: 'timer',
	polish: 'full'
};
const STRATEGIES: Strategy[] = ['shadow', 'route:jev', 'route:qwen'];
const FRONT_DOORS: FrontDoor[] = ['timer', 'jev', 'decision'];

function storage(): Storage | undefined {
	try {
		return typeof localStorage !== 'undefined' ? localStorage : undefined;
	} catch {
		return undefined;
	}
}

export function loadLabConfig(store: Storage | undefined = storage()): LabConfig {
	if (!store) return { ...DEFAULT_LAB_CONFIG };
	try {
		const raw = store.getItem(LAB_CONFIG_KEY);
		if (!raw) return { ...DEFAULT_LAB_CONFIG };
		const p = JSON.parse(raw);
		const pt = p?.pillThresholds;
		const ok =
			STRATEGIES.includes(p?.strategy) &&
			typeof p?.threshold === 'number' &&
			p.threshold >= 0.5 &&
			p.threshold <= 1 &&
			typeof p?.showBoth === 'boolean' &&
			typeof p?.coverageDebug === 'boolean' &&
			typeof pt?.hi === 'number' &&
			typeof pt?.lo === 'number' &&
			pt.lo >= 0 &&
			pt.lo < pt.hi &&
			pt.hi <= 1 &&
			FRONT_DOORS.includes(p?.frontDoor);
		return ok
			? {
					strategy: p.strategy,
					threshold: p.threshold,
					showBoth: p.showBoth,
					coverageDebug: p.coverageDebug,
					pillThresholds: { hi: pt.hi, lo: pt.lo },
					frontDoor: p.frontDoor,
					polish: p.polish === 'race' ? 'race' : 'full' // absent in older saved configs
				}
			: { ...DEFAULT_LAB_CONFIG };
	} catch {
		return { ...DEFAULT_LAB_CONFIG };
	}
}

export function saveLabConfig(config: LabConfig, store: Storage | undefined = storage()): void {
	if (!store) return;
	try {
		store.setItem(LAB_CONFIG_KEY, JSON.stringify(config));
	} catch {
		/* per-viewer convenience only */
	}
}

export function toRequestFields(config: LabConfig): LabRequestFields {
	const triage_route =
		config.strategy === 'route:jev'
			? { candidate: 'jev' as const, threshold: config.threshold }
			: config.strategy === 'route:qwen'
				? { candidate: 'qwen' as const, threshold: config.threshold }
				: null;
	return { triage_debug: config.showBoth, triage_route };
}

/** Page-level store; the lab page subscribes and persists on change. */
export const labConfig = writable<LabConfig>(loadLabConfig());
