import { API_URL } from '$lib/config.js';
import type { IntegrityFlag } from './checks';
import type { AssumedResult, DraftResult, GateRecord, GroupResult, ItemsResult, Region, SlimSheet, StackItem, StackSchema, StackUnit } from './types';

async function post<T>(token: string | null, path: string, body: unknown, keepalive = false): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/canvas/stack/${path}`, { method: 'POST', headers, body: JSON.stringify(body), keepalive });
	if (!res.ok) throw new Error(`stack ${path} ${res.status}`);
	return (await res.json()) as T;
}

export const fetchSchema = (token: string | null, body: { scan_type: string; clinical_history: string; template_id?: string | null }) =>
	post<StackSchema>(token, 'schema', body);

export const postGroup = (token: string | null, body: { scan_type: string; text: string; regions: Region[]; previous: StackUnit[] }) =>
	post<GroupResult>(token, 'group', body);

export const postClose = (token: string | null, body: { units: StackUnit[]; regions: Region[] }) =>
	post<GroupResult>(token, 'close', body);

export interface StackLog {
	session_id: string; scan_type: string; schema_key: string | null; schema_source: string | null; provisional: boolean;
	units: StackUnit[]; pills_derived: string[]; pills_jev: string[]; sections: string[]; structured_text: string;
	manual_moves: number; latency_ms: Record<string, number>; gate?: GateRecord | null; report_id?: string | null;
}
export const postLog = (token: string | null, body: StackLog) => post<{ ok: boolean }>(token, 'log', body, true);

export const postItems = (token: string | null, body: {
	scan_type: string; clinical_history: string; regions: string[]; dictation: string; abnormal: string[]; not_assessable?: string; removed?: string[]; tapped?: string[];
	referrals?: { question: string; region: string; sentences: string[] }[] | null;
	review?: boolean;
}) => post<ItemsResult>(token, 'items', body);

export const postAssumed = (token: string | null, body: {
	dictation: string; region_normals: Record<string, string[]>; abnormal: string[]; dictated_normal: string[]; removed?: string[]; owned?: string[]; touched?: string[];
	template_id?: string | null; clinical_history?: string;
}) => post<AssumedResult>(token, 'assumed', body);

/** The quiet re-check after an edit that leaves the abnormal findings unchanged: the rows on screen against the
 *  current dictation, no writer call. */
export const postRecheck = (token: string | null, body: { dictation: string; rows: StackItem[]; removed?: string[]; tapped?: string[] }) =>
	post<ItemsResult>(token, 'recheck', body);

/** Whether the abnormal findings changed materially since the last full review (fails to material). */
export const postChanged = (token: string | null, body: { before: string[]; after: string[] }) =>
	post<{ material: boolean; score: number | null }>(token, 'changed', body);

/** Whether the radiologist's own conclusion no longer reflects the findings (fails quiet). */
export const postConclusionCheck = (token: string | null, body: { conclusion: string; findings: string[] }) =>
	post<{ stale: boolean; score: number | null }>(token, 'conclusion-check', body);

/** The dictation integrity check (tier 1 code; tier 2 gpt-oss when asked and tier 1 is clean). */
export async function postDictationCheck(token: string | null, body: { findings: string; include_semantic: boolean; skip_tier1?: boolean; scan_type?: string; clinical_history?: string }): Promise<{ flags: IntegrityFlag[] }> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/dictation/check`, { method: 'POST', headers, body: JSON.stringify(body) });
	if (!res.ok) throw new Error(`dictation check ${res.status}`);
	return (await res.json()) as { flags: IntegrityFlag[] };
}

/** Unfinished sentences, judged by Jev: the scratchpad's only check for them (flags shaped as the dictation check's). */
export const postUnfinished = (token: string | null, body: { text: string }) => post<{ flags: IntegrityFlag[] }>(token, 'unfinished', body);

export const postSlimSheet = (token: string | null, body: { scan_type: string; clinical_history: string; template_id?: string | null }) =>
	post<SlimSheet>(token, 'slim-sheet', body);

export const postDraft = (token: string | null, body: { scan_type: string; clinical_history: string; findings: string }) =>
	post<DraftResult>(token, 'draft', body);

/** After Generate: link the report to the stack session (only the id; everything else is already logged). */
export const postReportId = (token: string | null, session_id: string, report_id: string) =>
	post<{ ok: boolean }>(token, 'log', { session_id, report_id }, true);

/** Local debugging only (the server answers 404 unless RR_STACK_DEBUG=1): a snapshot of an anomaly. */
export const postDebug = (token: string | null, body: Record<string, unknown>) =>
	post<{ ok: boolean }>(token, 'debug', body).catch(() => ({ ok: false }));
