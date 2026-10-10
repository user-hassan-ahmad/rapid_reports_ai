import { afterEach, describe, expect, it, vi } from 'vitest';
import { AI_MODE_KEYS, AI_MODE_STORAGE_KEY, DEFAULT_AI_MODE, readAiMode, writeAiMode } from './aiMode';

afterEach(() => {
	localStorage.removeItem(AI_MODE_STORAGE_KEY);
	vi.restoreAllMocks();
});

describe('AI highlights mode persistence', () => {
	it('maps modes to emphasis keys', () => {
		expect(AI_MODE_KEYS.key).toEqual(['ai']);
		expect(AI_MODE_KEYS.all).toEqual(['ai', 'normals']);
		expect(AI_MODE_KEYS.off).toEqual([]);
		expect(DEFAULT_AI_MODE).toBe('key');
	});

	it('round-trips each mode through localStorage rv_ai_mode', () => {
		expect(readAiMode()).toBe('key');
		for (const m of ['all', 'off', 'key'] as const) {
			writeAiMode(m);
			expect(localStorage.getItem('rv_ai_mode')).toBe(m);
			expect(readAiMode()).toBe(m);
		}
	});

	it('ignores junk and survives a blocked store', () => {
		localStorage.setItem(AI_MODE_STORAGE_KEY, 'loud');
		expect(readAiMode()).toBe('key');
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		expect(readAiMode()).toBe('key');
		expect(() => writeAiMode('off')).not.toThrow();
	});
});
