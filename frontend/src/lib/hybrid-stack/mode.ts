// The latched stack mode (integration spec §9.2): read from /api/settings/status at "Set up workspace", never swapped
// mid-session. A failed status call is retried, never read as "old flow"; a server with no `stack` field is off.
import { writable } from 'svelte/store';
import { API_URL } from '$lib/config.js';

export type StackStatus = { stack: boolean; copilot: boolean; library: boolean };

/** The server status as last read (null: not read yet). */
export const stackStatus = writable<StackStatus | null>(null);
/** The latched mode: true once a workspace was set up with the stack on (post-generation reads it, D4/D13). */
export const stackMode = writable<boolean>(false);

export function stackOn(status: { stack?: unknown } | null | undefined): boolean {
	return status?.stack === true;
}

const BACKOFF_MS = [250, 500, 1000];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Fetch the status (retrying with backoff), latch and return the mode. Throws after the last failure. */
export async function latchStackMode(fetchStatus: () => Promise<Response>, tries = 3): Promise<boolean> {
	let last: unknown = null;
	for (let i = 0; i < tries; i++) {
		if (i > 0) await sleep(BACKOFF_MS[Math.min(i - 1, BACKOFF_MS.length - 1)]);
		try {
			const res = await fetchStatus();
			if (!res.ok) throw new Error(`status ${res.status}`);
			const data = await res.json();
			const on = stackOn(data);
			stackStatus.set({ stack: on, copilot: data?.stack_copilot === true, library: data?.protocol_library === true });
			stackMode.set(on);
			return on;
		} catch (e) {
			last = e;
		}
	}
	throw last instanceof Error ? last : new Error('status unavailable');
}

/** The status fetch the hosts latch with. */
export function statusFetcher(token: string | null): () => Promise<Response> {
	// A stalled request is a failure to retry, never a spinner that never ends
	return () => fetch(`${API_URL}/api/settings/status`, {
		headers: token ? { Authorization: `Bearer ${token}` } : {},
		signal: AbortSignal.timeout(5000)
	});
}

/** The page-load status primes the mode (D4/D13): a report opened from History before any Set up still skips the
 *  legacy post-generation calls. Only ever turns it on; the tabs latch their own sessions at Set up. */
export function primeStackMode(status: { stack?: unknown } | null | undefined): void {
	if (stackOn(status)) stackMode.set(true);
}
