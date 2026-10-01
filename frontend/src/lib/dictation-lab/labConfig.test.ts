import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import {
	DEFAULT_LAB_CONFIG,
	labConfig,
	loadLabConfig,
	saveLabConfig
} from './labConfig';
import type { LabConfig } from './types';

describe('persistence', () => {
	it('falls back to defaults when storage is unavailable or corrupt', () => {
		const fake = {
			getItem: () => '{not json',
			setItem: () => {
				throw new Error('quota');
			}
		} as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
		expect(() => saveLabConfig({ ...DEFAULT_LAB_CONFIG, polish: 'race' }, fake)).not.toThrow();
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
			coverageDebug: false,
			pillThresholds: { hi: 0.9, lo: 0.3 },
			frontDoor: 'decision',
			polish: 'full'
		};
		saveLabConfig(cfg, fake);
		expect(loadLabConfig(fake)).toEqual(cfg);
	});
	it('rejects out-of-range or unknown values', () => {
		const fake = {
			getItem: () => JSON.stringify({ ...DEFAULT_LAB_CONFIG, frontDoor: 'jev', coverageDebug: 'yes' })
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
	it('round-trips the racing polish switch, and older saved configs default to full', () => {
		const mem: Record<string, string> = {};
		const fake = {
			getItem: (k: string) => mem[k] ?? null,
			setItem: (k: string, v: string) => {
				mem[k] = v;
			}
		} as unknown as Storage;
		const cfg: LabConfig = { ...DEFAULT_LAB_CONFIG, frontDoor: 'decision', polish: 'race' };
		saveLabConfig(cfg, fake);
		expect(loadLabConfig(fake)).toEqual(cfg);
		const { polish: _drop, ...old } = cfg;
		mem['rr_lab_config'] = JSON.stringify(old);
		expect(loadLabConfig(fake).polish).toBe('full');
	});
	it('exposes a store seeded from defaults', () => {
		expect(get(labConfig)).toEqual(DEFAULT_LAB_CONFIG);
	});
});
