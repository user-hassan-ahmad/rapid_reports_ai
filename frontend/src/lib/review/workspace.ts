// The rail's per-report workspace (spec §10.2, plan Task E1): tab, expanded items, density and the last text_hash,
// stored in `reports.workspace_state` via GET/PUT /api/reports/{id}/workspace. Saves are debounced (1 s, latest
// state wins) and never throw: losing a workspace save costs the user a collapsed card, not their report.
import { get } from 'svelte/store';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import type { Density } from './editor/theme';

export interface WorkspaceState {
	tab: string;
	expanded_ids: string[];
	density: Density;
	last_text_hash: string | null;
}

async function request(reportId: string, state?: WorkspaceState): Promise<WorkspaceState | null> {
	const headers: Record<string, string> = { Authorization: `Bearer ${get(token)}` };
	const init: RequestInit = { method: state === undefined ? 'GET' : 'PUT', headers };
	if (state !== undefined) {
		headers['Content-Type'] = 'application/json';
		init.body = JSON.stringify(state);
	}
	const res = await fetch(`${API_URL}/api/reports/${encodeURIComponent(reportId)}/workspace`, init);
	let data: { success?: boolean; error?: string; workspace?: WorkspaceState | null } | null = null;
	try {
		data = await res.json();
	} catch {
		data = null;
	}
	if (!res.ok || !data || data.success !== true) {
		throw new Error(data?.error || `workspace request failed (${res.status})`);
	}
	return data.workspace ?? null;
}

/** The saved workspace, or null when the report has none yet. */
export function loadWorkspace(reportId: string): Promise<WorkspaceState | null> {
	return request(reportId);
}

/** Store the workspace now; returns what the server stored. A 422 (bad shape) throws. */
export async function saveWorkspace(reportId: string, state: WorkspaceState): Promise<WorkspaceState> {
	return (await request(reportId, state)) as WorkspaceState;
}

export interface WorkspaceSaver {
	/** Queue `state`; it is saved `delayMs` after the last call. */
	schedule(state: WorkspaceState): void;
	/** Save the pending state now (e.g. on leaving the report); a no-op when nothing is pending. */
	flush(): Promise<void>;
	/** Drop the pending state without saving. */
	cancel(): void;
}

export function createWorkspaceSaver(
	reportId: string,
	opts: {
		delayMs?: number;
		save?: (reportId: string, state: WorkspaceState) => Promise<unknown>;
		onError?: (e: Error) => void;
	} = {}
): WorkspaceSaver {
	const delayMs = opts.delayMs ?? 1000;
	const save = opts.save ?? saveWorkspace;
	const onError = opts.onError ?? ((e: Error) => console.warn('workspace save failed', e));
	let pending: WorkspaceState | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;

	function clear() {
		if (timer !== null) clearTimeout(timer);
		timer = null;
	}

	async function flush(): Promise<void> {
		clear();
		const state = pending;
		pending = null;
		if (!state) return;
		try {
			await save(reportId, state);
		} catch (e) {
			onError(e instanceof Error ? e : new Error(String(e)));
		}
	}

	return {
		schedule(state) {
			pending = state;
			clear();
			timer = setTimeout(() => void flush(), delayMs);
		},
		flush,
		cancel() {
			clear();
			pending = null;
		}
	};
}
