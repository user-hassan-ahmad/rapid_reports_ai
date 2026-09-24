import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import {
	DEFAULT_LAB_CONFIG,
	labConfig,
	loadLabConfig,
	saveLabConfig,
	toRequestFields
} from './labConfig';

describe('toRequestFields', () => {
	it('shadow strategy sends debug only when showBoth', () => {
		expect(toRequestFields({ strategy: 'shadow', threshold: 0.9, showBoth: true })).toEqual({
			triage_debug: true,
			triage_route: null
		});
		expect(toRequestFields({ strategy: 'shadow', threshold: 0.9, showBoth: false })).toEqual({
			triage_debug: false,
			triage_route: null
		});
	});
	it('route strategies set the candidate and threshold', () => {
		expect(toRequestFields({ strategy: 'route:jev', threshold: 0.85, showBoth: false })).toEqual({
			triage_debug: false,
			triage_route: { candidate: 'jev', threshold: 0.85 }
		});
		expect(
			toRequestFields({ strategy: 'route:qwen', threshold: 0.7, showBoth: true }).triage_route
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
		saveLabConfig({ strategy: 'route:jev', threshold: 0.75, showBoth: true }, fake);
		expect(loadLabConfig(fake)).toEqual({ strategy: 'route:jev', threshold: 0.75, showBoth: true });
	});
	it('rejects out-of-range or unknown values', () => {
		const fake = {
			getItem: () => JSON.stringify({ strategy: 'route:gpt', threshold: 7, showBoth: 'yes' })
		} as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
	});
	it('exposes a store seeded from defaults', () => {
		expect(get(labConfig)).toEqual(DEFAULT_LAB_CONFIG);
	});
});
