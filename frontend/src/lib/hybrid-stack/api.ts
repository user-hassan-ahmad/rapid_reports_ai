import { API_URL } from '$lib/config.js';
import type { ChipsResult, DraftResult, GateRecord, GroupResult, Region, StackSchema, StackUnit } from './types';

async function post<T>(token: string | null, path: string, body: unknown, keepalive = false): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/canvas/stack/${path}`, { method: 'POST', headers, body: JSON.stringify(body), keepalive });
	if (!res.ok) throw new Error(`stack ${path} ${res.status}`);
	return (await res.json()) as T;
}

export const fetchSchema = (token: string | null, body: { scan_type: string; clinical_history: string; template_id?: string | null }) =>
	post<StackSchema>(token, 'schema', body);

export const postGroup = (token: string | null, body: { scan_type: string; text: string; regions: Region[]; previous: StackUnit[]; chips?: string[] }) =>
	post<GroupResult>(token, 'group', body);

export const postClose = (token: string | null, body: { units: StackUnit[]; regions: Region[] }) =>
	post<GroupResult>(token, 'close', body);

export interface StackLog {
	session_id: string; scan_type: string; schema_key: string | null; schema_source: string | null; provisional: boolean;
	units: StackUnit[]; pills_derived: string[]; pills_jev: string[]; sections: string[]; structured_text: string;
	manual_moves: number; latency_ms: Record<string, number>; gate?: GateRecord | null; report_id?: string | null;
}
export const postLog = (token: string | null, body: StackLog) => post<{ ok: boolean }>(token, 'log', body, true);

export const postChips = (token: string | null, body: { scan_type: string; clinical_history: string; region: string; sentences: string[]; dictation: string }) =>
	post<ChipsResult>(token, 'chips', body);

export const postDraft = (token: string | null, body: { scan_type: string; clinical_history: string; findings: string }) =>
	post<DraftResult>(token, 'draft', body);

/** After Generate: link the report to the stack session (only the id; everything else is already logged). */
export const postReportId = (token: string | null, session_id: string, report_id: string) =>
	post<{ ok: boolean }>(token, 'log', { session_id, report_id }, true);
