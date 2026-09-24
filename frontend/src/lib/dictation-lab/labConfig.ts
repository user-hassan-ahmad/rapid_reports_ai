import { writable } from 'svelte/store';
import type { LabConfig, LabRequestFields, Strategy } from './types';

export const LAB_CONFIG_KEY = 'rr_lab_config';
export const DEFAULT_LAB_CONFIG: LabConfig = { strategy: 'shadow', threshold: 0.9, showBoth: true };
const STRATEGIES: Strategy[] = ['shadow', 'route:jev', 'route:qwen'];

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
		const ok =
			STRATEGIES.includes(p?.strategy) &&
			typeof p?.threshold === 'number' &&
			p.threshold >= 0.5 &&
			p.threshold <= 1 &&
			typeof p?.showBoth === 'boolean';
		return ok
			? { strategy: p.strategy, threshold: p.threshold, showBoth: p.showBoth }
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
