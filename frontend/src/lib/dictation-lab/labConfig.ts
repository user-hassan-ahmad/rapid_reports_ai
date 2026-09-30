import { writable } from 'svelte/store';
import type { FrontDoor, LabConfig } from './types';

export const LAB_CONFIG_KEY = 'rr_lab_config';
export const DEFAULT_LAB_CONFIG: LabConfig = {
	coverageDebug: true,
	pillThresholds: { hi: 0.8, lo: 0.4 },
	frontDoor: 'timer',
	polish: 'full'
};
const FRONT_DOORS: FrontDoor[] = ['timer', 'decision'];

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
			typeof p?.coverageDebug === 'boolean' &&
			typeof pt?.hi === 'number' &&
			typeof pt?.lo === 'number' &&
			pt.lo >= 0 &&
			pt.lo < pt.hi &&
			pt.hi <= 1 &&
			FRONT_DOORS.includes(p?.frontDoor);
		return ok
			? {
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

/** Page-level store; the lab page subscribes and persists on change. */
export const labConfig = writable<LabConfig>(loadLabConfig());
