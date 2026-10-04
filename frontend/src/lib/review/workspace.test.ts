import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import { createWorkspaceSaver, loadWorkspace, saveWorkspace, type WorkspaceState } from './workspace';

const STATE: WorkspaceState = {
	tab: 'review',
	expanded_ids: ['a1'],
	density: 'quiet',
	last_text_hash: '47597f087ff5d076'
};

function respond(body: unknown, status = 200) {
	return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

function call(fetchMock: ReturnType<typeof vi.fn>, n = 0) {
	const [url, init] = fetchMock.mock.calls[n] as [string, RequestInit];
	return { url, init, headers: init.headers as Record<string, string> };
}

beforeEach(() => token.set('tok-1' as never));
afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
	token.set(null);
});

describe('loadWorkspace', () => {
	it('GETs the workspace with the bearer header and returns it', async () => {
		const f = respond({ success: true, workspace: STATE });
		vi.stubGlobal('fetch', f);
		expect(await loadWorkspace('r1')).toEqual(STATE);
		const { url, init, headers } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r1/workspace`);
		expect(init.method ?? 'GET').toBe('GET');
		expect(headers.Authorization).toBe('Bearer tok-1');
	});

	it('returns null when nothing is saved', async () => {
		vi.stubGlobal('fetch', respond({ success: true, workspace: null }));
		expect(await loadWorkspace('r1')).toBeNull();
	});

	it('throws on success:false', async () => {
		vi.stubGlobal('fetch', respond({ success: false, error: 'Report not found' }));
		await expect(loadWorkspace('r1')).rejects.toThrow('Report not found');
	});
});

describe('saveWorkspace', () => {
	it('PUTs the state as JSON and returns the stored workspace', async () => {
		const f = respond({ success: true, workspace: STATE });
		vi.stubGlobal('fetch', f);
		expect(await saveWorkspace('r 1', STATE)).toEqual(STATE);
		const { url, init, headers } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r%201/workspace`);
		expect(init.method).toBe('PUT');
		expect(headers['Content-Type']).toBe('application/json');
		expect(headers.Authorization).toBe('Bearer tok-1');
		expect(JSON.parse(init.body as string)).toEqual(STATE);
	});

	it('a 422 surfaces as an error', async () => {
		vi.stubGlobal('fetch', respond({ detail: [{ msg: 'bad' }] }, 422));
		await expect(saveWorkspace('r1', STATE)).rejects.toThrow('422');
	});
});

describe('createWorkspaceSaver', () => {
	it('debounces: one save, 1 s after the last change, with the latest state', async () => {
		vi.useFakeTimers();
		const save = vi.fn(async (_id: string, s: WorkspaceState) => s);
		const saver = createWorkspaceSaver('r1', { save });
		saver.schedule({ ...STATE, tab: 'guidelines' });
		await vi.advanceTimersByTimeAsync(600);
		saver.schedule({ ...STATE, density: 'full' });
		await vi.advanceTimersByTimeAsync(999);
		expect(save).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		expect(save).toHaveBeenCalledTimes(1);
		expect(save).toHaveBeenCalledWith('r1', { ...STATE, density: 'full' });
	});

	it('flush sends the pending state now, and only once', async () => {
		vi.useFakeTimers();
		const save = vi.fn(async (_id: string, s: WorkspaceState) => s);
		const saver = createWorkspaceSaver('r1', { save });
		saver.schedule(STATE);
		await saver.flush();
		expect(save).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(2000);
		expect(save).toHaveBeenCalledTimes(1);
		await saver.flush();
		expect(save).toHaveBeenCalledTimes(1);
	});

	it('cancel drops the pending save', async () => {
		vi.useFakeTimers();
		const save = vi.fn(async (_id: string, s: WorkspaceState) => s);
		const saver = createWorkspaceSaver('r1', { save });
		saver.schedule(STATE);
		saver.cancel();
		await vi.advanceTimersByTimeAsync(2000);
		expect(save).not.toHaveBeenCalled();
	});

	it('a failed save is reported, not thrown: workspace state is a convenience', async () => {
		vi.useFakeTimers();
		const onError = vi.fn();
		const save = vi.fn(async () => {
			throw new Error('boom');
		});
		const saver = createWorkspaceSaver('r1', { save, onError, delayMs: 10 });
		saver.schedule(STATE);
		await vi.advanceTimersByTimeAsync(10);
		expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }));
	});
});
