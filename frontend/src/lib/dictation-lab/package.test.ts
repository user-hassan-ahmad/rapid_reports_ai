import { describe, expect, it } from 'vitest';
import { PACKAGE_CONFIG, dictationV2On, effectiveConfig } from './package';
import { DEFAULT_LAB_CONFIG } from './labConfig';

const store = (v: string | null) => ({ getItem: (k: string) => (k === 'rr_dictation_v2' ? v : null) }) as Storage;

describe('rr_dictation_v2: the dictation package, on by default where the server allows it', () => {
	it('is on unless the browser opted out with "0"', () => {
		expect(dictationV2On(store(null))).toBe(true);
		expect(dictationV2On(store('1'))).toBe(true);
		expect(dictationV2On(store('0'))).toBe(false);
		expect(dictationV2On(undefined)).toBe(true);
	});

	it('the package runs what the lab ran: decision-first with the raced lean polish, no debug extras', () => {
		expect(PACKAGE_CONFIG.frontDoor).toBe('decision');
		expect(PACKAGE_CONFIG.polish).toBe('race');
		expect(PACKAGE_CONFIG.showBoth).toBe(false);
		expect(PACKAGE_CONFIG.coverageDebug).toBe(false);
	});

	it('runs only where the server allows it (RR_DICTATION_V2 is the kill switch)', () => {
		expect(effectiveConfig(null, store(null), true)).toBe(PACKAGE_CONFIG);
		expect(effectiveConfig(null, store(null), false)).toBeNull();
		expect(effectiveConfig(null, store('0'), true)).toBeNull();
	});

	it('the lab page keeps its own config', () => {
		expect(effectiveConfig(DEFAULT_LAB_CONFIG, store('0'), false)).toBe(DEFAULT_LAB_CONFIG);
	});
});
