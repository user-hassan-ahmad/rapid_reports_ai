import { afterEach, describe, expect, it, vi } from 'vitest';
import { installLegacyGuard, isLegacy, legacyHits } from './legacyGuard';

const API = 'http://localhost:8000';
afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	legacyHits.length = 0;
});

describe('client tripwire (spec §9.5)', () => {
	it('test_guard_warns_on_legacy_urls', async () => {
		const orig = vi.fn(async () => new Response('{}'));
		vi.stubGlobal('fetch', orig);
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		let active = true;
		const uninstall = installLegacyGuard(() => active);
		const legacy = [
			`${API}/api/quick-report/analyse`,
			`${API}/api/canvas/sections`,
			`${API}/api/canvas/sections-from-template`,
			`${API}/api/reports/r1/enhance`,
			`${API}/api/audit`,
			`${API}/api/audit/a1/criteria/c1`,
			`${API}/api/reports/r1/validation-status`,
			`${API}/api/templates/t1/prepare`,
			`${API}/api/canvas/review`
		];
		for (const u of legacy) await fetch(u, { method: 'POST' });
		await fetch(`${API}/api/canvas/process`, { method: 'POST', body: JSON.stringify({ mode: 'structured' }) });
		// not legacy: the stack's own calls and the decision door's clean fallback
		await fetch(`${API}/api/canvas/stack/generate`, { method: 'POST' });
		await fetch(`${API}/api/canvas/process`, { method: 'POST', body: JSON.stringify({ mode: 'clean' }) });
		await fetch(`${API}/api/canvas/stack/guidelines/match`, { method: 'POST' });
		expect(legacyHits).toEqual([...legacy, `${API}/api/canvas/process`]);
		expect(warn).toHaveBeenCalledWith('[legacy.call]', `${API}/api/quick-report/analyse`);
		expect(orig).toHaveBeenCalledTimes(legacy.length + 4); // warned, never blocked
		active = false;
		await fetch(`${API}/api/quick-report/analyse`, { method: 'POST' });
		expect(legacyHits).toHaveLength(legacy.length + 1);
		uninstall();
	});

	it('isLegacy reads URL objects and Requests the same way', () => {
		expect(isLegacy(`${API}/api/quick-report/generate`)).toBe(true);
		expect(isLegacy(`${API}/api/templates/t1/generate`)).toBe(true);
		expect(isLegacy(`${API}/api/canvas/stack/schema`)).toBe(false);
		expect(isLegacy(`${API}/api/canvas/bundle`)).toBe(false);
	});

	it('template authoring is not a legacy call', () => {
		const API = 'http://x';
		expect(isLegacy(`${API}/api/templates/skill-sheet/generate-test-case`)).toBe(false);
		expect(isLegacy(`${API}/api/templates/t1/prepare?x=1`)).toBe(true);
	});
});
