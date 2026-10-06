// Review API client (spec §10.3). The only place the frontend calls the review endpoints.
import { get } from 'svelte/store';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import type {
	ProbeResponse,
	ReprepareResponse,
	RerunResponse,
	ReviewItem,
	ReviewResponse,
	UserCommand
} from './types';

async function request<T>(path: string, body?: unknown): Promise<T> {
	const headers: Record<string, string> = { Authorization: `Bearer ${get(token)}` };
	const init: RequestInit = { method: body === undefined ? 'GET' : 'POST', headers };
	if (body !== undefined) {
		headers['Content-Type'] = 'application/json';
		init.body = JSON.stringify(body);
	}
	const res = await fetch(`${API_URL}/api/reports/${path}`, init);
	let data: { success?: boolean; error?: string } | null = null;
	try {
		data = await res.json();
	} catch {
		data = null;
	}
	if (!res.ok || !data || data.success !== true) {
		throw new Error(data?.error || `review request failed (${res.status})`);
	}
	return data as T;
}

/** The latest run and its items, including assumed_normal rows (editor decorations use them). */
export function getReview(reportId: string): Promise<ReviewResponse> {
	return request<ReviewResponse>(`${encodeURIComponent(reportId)}/review?include=normals`);
}

/** Record a user command on an item; returns the updated item. A 422 (engine status, bad transition) throws. */
export async function postEvent(
	reportId: string,
	itemId: string,
	command: UserCommand,
	textHash: string | null = null,
	detail: Record<string, unknown> = {}
): Promise<ReviewItem> {
	const data = await request<{ success: true; item: ReviewItem }>(
		`${encodeURIComponent(reportId)}/review/items/${encodeURIComponent(itemId)}/events`,
		{ command, text_hash: textHash, detail }
	);
	return data.item;
}

export function probe(
	reportId: string,
	text: string,
	textHash: string,
	changedRanges: [number, number][] = []
): Promise<ProbeResponse> {
	return request<ProbeResponse>(`${encodeURIComponent(reportId)}/review/probe`, {
		text,
		text_hash: textHash,
		changed_ranges: changedRanges
	});
}

export function reprepare(
	reportId: string,
	itemIds: string[],
	text: string,
	textHash: string
): Promise<ReprepareResponse> {
	return request<ReprepareResponse>(`${encodeURIComponent(reportId)}/review/reprepare`, {
		item_ids: itemIds,
		text,
		text_hash: textHash
	});
}

export function rerun(reportId: string, text?: string): Promise<RerunResponse> {
	return request<RerunResponse>(`${encodeURIComponent(reportId)}/review/rerun`, { text: text ?? null });
}
