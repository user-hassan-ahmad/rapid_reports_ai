import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import {
	DEFAULT_LAB_CONFIG,
	labConfig,
	loadLabConfig,
	saveLabConfig,
	toRequestFields
} from './labConfig';
import type { LabConfig } from './types';

const base: Omit<LabConfig, 'strategy' | 'threshold' | 'showBoth'> = {
	coverageDebug: true,
	pillThresholds: { hi: 0.8, lo: 0.4 },
	frontDoor: 'timer'
};

describe('toRequestFields', () => {
	it('shadow strategy sends debug only when showBoth', () => {
		expect(toRequestFields({ strategy: 'shadow', threshold: 0.9, showBoth: true, ...base })).toEqual({
			triage_debug: true,
			triage_route: null
		});
		expect(toRequestFields({ strategy: 'shadow', threshold: 0.9, showBoth: false, ...base })).toEqual({
			triage_debug: false,
			triage_route: null
		});
	});
	it('route strategies set the candidate and threshold', () => {
		expect(toRequestFields({ strategy: 'route:jev', threshold: 0.85, showBoth: false, ...base })).toEqual({
			triage_debug: false,
			triage_route: { candidate: 'jev', threshold: 0.85 }
		});
		expect(
			toRequestFields({ strategy: 'route:qwen', threshold: 0.7, showBoth: true, ...base }).triage_route
		).toEqual({ candidate: 'qwen', threshold: 0.7 });
	});
});

describe('persistence', () => {
	it('falls back to defaults when storage is unavailable or corrupt', () => {
		const fake = {
			getItem: () => '{not json',
			setItem: () => {
				throw new Error('quota');
			}
		} as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
		expect(() => saveLabConfig({ ...DEFAULT_LAB_CONFIG, threshold: 0.6 }, fake)).not.toThrow();
		expect(loadLabConfig(undefined)).toEqual(DEFAULT_LAB_CONFIG);
	});
	it('round-trips through a storage object', () => {
		const mem: Record<string, string> = {};
		const fake = {
			getItem: (k: string) => mem[k] ?? null,
			setItem: (k: string, v: string) => {
				mem[k] = v;
			}
		} as unknown as Storage;
		const cfg: LabConfig = {
			strategy: 'route:jev',
			threshold: 0.75,
			showBoth: true,
			coverageDebug: false,
			pillThresholds: { hi: 0.9, lo: 0.3 },
			frontDoor: 'jev'
		};
		saveLabConfig(cfg, fake);
		expect(loadLabConfig(fake)).toEqual(cfg);
	});
	it('rejects out-of-range or unknown values', () => {
		const fake = {
			getItem: () => JSON.stringify({ strategy: 'route:gpt', threshold: 7, showBoth: 'yes' })
		} as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
	});
	it('rejects inverted pill thresholds', () => {
		const fake = {
			getItem: () => JSON.stringify({ ...DEFAULT_LAB_CONFIG, pillThresholds: { hi: 0.3, lo: 0.6 } })
		} as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
	});
	it('round-trips the decision-first front door', () => {
		const mem: Record<string, string> = {};
		const fake = {
			getItem: (k: string) => mem[k] ?? null,
			setItem: (k: string, v: string) => {
				mem[k] = v;
			}
		} as unknown as Storage;
		const cfg: LabConfig = { ...DEFAULT_LAB_CONFIG, frontDoor: 'decision' };
		saveLabConfig(cfg, fake);
		expect(loadLabConfig(fake)).toEqual(cfg);
	});
	it('exposes a store seeded from defaults', () => {
		expect(get(labConfig)).toEqual(DEFAULT_LAB_CONFIG);
	});
});
