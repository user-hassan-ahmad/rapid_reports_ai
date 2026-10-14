import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { latchStackMode, primeStackMode, showLegacyCopilot, stackMode, stackOn, statusFetcher } from './mode';

describe('latched stack mode', () => {
	it('test_latch_retries_and_never_falls_back', async () => {
		const ok = new Response(JSON.stringify({ stack: true }));
		const f = vi.fn().mockRejectedValueOnce(new Error('net')).mockResolvedValueOnce(ok);
		expect(await latchStackMode(f, 3)).toBe(true);
		expect(f).toHaveBeenCalledTimes(2);
		const bad = vi.fn().mockRejectedValue(new Error('net'));
		await expect(latchStackMode(bad, 2)).rejects.toThrow();
	});
	it('a non-OK status reply is a failure to retry, not "old flow"', async () => {
		const f = vi.fn()
			.mockResolvedValueOnce(new Response('', { status: 502 }))
			.mockResolvedValueOnce(new Response(JSON.stringify({ stack: true })));
		expect(await latchStackMode(f, 3)).toBe(true);
		expect(f).toHaveBeenCalledTimes(2);
	});
	it('the latched value reaches the stackMode store', async () => {
		await latchStackMode(async () => new Response(JSON.stringify({ stack: false })), 1);
		expect(get(stackMode)).toBe(false);
		await latchStackMode(async () => new Response(JSON.stringify({ stack: true })), 1);
		expect(get(stackMode)).toBe(true);
	});
	it('reads a missing field as off (old server)', () => {
		expect(stackOn({})).toBe(false);
		expect(stackOn(null)).toBe(false);
		expect(stackOn({ stack: true })).toBe(true);
	});

	it('the page-load status primes the mode, so post-generation knows before any Set up', () => {
		stackMode.set(false);
		primeStackMode({ stack: true });
		expect(get(stackMode)).toBe(true);
		stackMode.set(false);
		primeStackMode({ stack: false });
		primeStackMode({});
		expect(get(stackMode)).toBe(false);
	});
	it('the status fetch gives up on a stalled request', () => {
		const f = vi.fn(async (_url: string, _init?: RequestInit) => new Response('{}'));
		vi.stubGlobal('fetch', f);
		void statusFetcher('t')();
		const init = f.mock.calls[0][1] ?? {};
		expect(init.signal).toBeInstanceOf(AbortSignal);
		vi.unstubAllGlobals();
	});
	it('the legacy Copilot sidebar and its quick-actions strip never show in stack mode (D13)', () => {
		expect(showLegacyCopilot(true)).toBe(false);
		expect(showLegacyCopilot(false)).toBe(true);
	});
});
