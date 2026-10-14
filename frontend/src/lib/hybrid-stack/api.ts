import { API_URL } from '$lib/config.js';
import { readSSEStream } from '$lib/utils/sse';
import type { IntegrityFlag } from './checks';
import type { ProtocolSearch } from './protocol';
import type { AssumedResult, DraftResult, GateRecord, GroupResult, ItemsResult, Region, SlimSheet, StackItem, StackSchema, StackUnit, ValuesResult } from './types';

/** A refused stack call, with the server's own message when it sent one (e.g. /schema refusing a template, D15). */
export class StackHttpError extends Error {
	constructor(path: string, readonly status: number, readonly detail: string | null) {
		super(`stack ${path} ${status}`);
	}
}

async function post<T>(token: string | null, path: string, body: unknown, keepalive = false, timeoutMs?: number): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const signal = timeoutMs ? AbortSignal.timeout(timeoutMs) : undefined;
	const res = await fetch(`${API_URL}/api/canvas/stack/${path}`, { method: 'POST', headers, body: JSON.stringify(body), keepalive, signal });
	if (!res.ok) {
		let detail: string | null = null;
		try {
			const d = (await res.json())?.detail;
			detail = typeof d === 'string' ? d : null;
		} catch { /* no JSON body */ }
		throw new StackHttpError(path, res.status, detail);
	}
	return (await res.json()) as T;
}

/** The dictation check and the assumed check give up after this long; Confirm never waits on them forever. */
const CHECK_TIMEOUT_MS = 25000;

type PickFields = { protocol_id?: string; phases?: string[]; laterality?: string | null };

export const fetchSchema = (token: string | null, body: { scan_type: string; clinical_history: string; template_id?: string | null } & PickFields) =>
	post<StackSchema>(token, 'schema', body);

export const searchProtocols = (token: string | null, body: { q: string; rerank: boolean }) =>
	post<ProtocolSearch>(token, 'protocols/search', body);

export const postNotListed = (token: string | null, body: { q: string }) =>
	post<{ ok: boolean }>(token, 'protocols/not-listed', body);

export const postGroup = (token: string | null, body: { scan_type: string; text: string; regions: Region[]; previous: StackUnit[] }) =>
	post<GroupResult>(token, 'group', body);

export const postClose = (token: string | null, body: { units: StackUnit[]; regions: Region[] }) =>
	post<GroupResult>(token, 'close', body);

export interface StackLog {
	session_id: string; scan_type: string; schema_key: string | null; schema_source: string | null; provisional: boolean;
	units: StackUnit[]; pills_derived: string[]; pills_jev: string[]; sections: string[]; structured_text: string;
	manual_moves: number; latency_ms: Record<string, number>; gate?: GateRecord | null; report_id?: string | null;
	template_id?: string | null; // template sessions: the server stamps the sheet (null: quick)
	/** Copilot session record (copilot/session log()): keys, kinds, counts and ms only, never text; capped server-side. */
	copilot?: Record<string, unknown>;
}
export const postLog = (token: string | null, body: StackLog) => post<{ ok: boolean }>(token, 'log', body, true);

export const postItems = (token: string | null, body: {
	scan_type: string; clinical_history: string; regions: string[]; dictation: string; abnormal: string[]; not_assessable?: string; removed?: string[]; tapped?: string[];
	referrals?: { question: string; region: string; sentences: string[] }[] | null;
	review?: boolean;
	template_id?: string | null;
}) => post<ItemsResult>(token, 'items', body);

export const postAssumed = (token: string | null, body: {
	dictation: string; region_normals: Record<string, string[]>; abnormal: string[]; removed?: string[]; owned?: string[];
	template_id?: string | null; clinical_history?: string; region_text?: Record<string, string>;
	rules?: Record<string, number> | null; confirm?: boolean;
}) => post<AssumedResult>(token, 'assumed', body, false, CHECK_TIMEOUT_MS); // a timeout fails open, as an error does

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
	// A timeout rejects like an error: the caller's catch fails open and Confirm stops waiting on the check.
	const res = await fetch(`${API_URL}/api/dictation/check`, { method: 'POST', headers, body: JSON.stringify(body), signal: AbortSignal.timeout(CHECK_TIMEOUT_MS) });
	if (!res.ok) throw new Error(`dictation check ${res.status}`);
	return (await res.json()) as { flags: IntegrityFlag[] };
}

/** Unfinished sentences, judged by Jev: the scratchpad's only check for them (flags shaped as the dictation check's). */
export const postUnfinished = (token: string | null, body: { text: string }) =>
	post<{ flags: IntegrityFlag[] }>(token, 'unfinished', body, false, CHECK_TIMEOUT_MS); // paired with the dictation check: a timeout fails open

/** The slim sheet. With the session's structure_key (D26) only the key is sent: the server reads the resolution from
 *  it, never from the request; without one (stack off, old server) today's fields. */
export const postSlimSheet = (token: string | null, body: { scan_type: string; clinical_history: string; template_id?: string | null; structure_key?: string | null } & PickFields) => {
	const { structure_key, ...rest } = body;
	return post<SlimSheet>(token, 'slim-sheet', structure_key ? { structure_key } : rest);
};
/** The value cluster's smart fill: the template's required values filled from the dictation or open (fails open). */
export const postValues = (token: string | null, body: { dictation: string; template_id: string | null }) =>
	post<ValuesResult>(token, 'values', body);

/** The conclusion draft: units + groups; the server builds the findings text with the one builder (P2b). */
export const postDraft = (token: string | null, body: { units: StackUnit[]; groups: string[]; scan_type: string; clinical_history: string }) =>
	post<DraftResult>(token, 'draft', body);

/** One Generate for quick and template stack sessions (integration spec §5): POST /api/canvas/stack/generate. */
export interface StackGenerateBody {
	kind: 'quick' | 'template';
	template_id?: string;
	variables?: Record<string, string>;
	scan_type: string;
	history: string;
	structure_key: string;
	units: StackUnit[];
	groups: string[];
	gate: GateRecord;
}

export function stackGenerateBody(a: {
	kind: 'quick' | 'template'; templateId?: string; variables?: Record<string, string>; scanType: string;
	history: string; structureKey: string; units: StackUnit[]; groups: string[]; gate: GateRecord;
}): StackGenerateBody {
	const variables = Object.fromEntries(Object.entries(a.variables ?? {}).filter(([k]) => k !== 'FINDINGS'));
	return {
		kind: a.kind, ...(a.templateId ? { template_id: a.templateId } : {}),
		...(a.kind === 'template' ? { variables } : {}), scan_type: a.scanType, history: a.history,
		structure_key: a.structureKey, units: a.units, groups: a.groups, gate: a.gate
	};
}

export const STACK_SWITCHED_OFF = 'The workspace was switched off; your dictation is kept. Set up again.';
const GENERATE_FAILED = 'Report generation failed. Please try again.';

/** Stream the stack Generate: `candidate` (the saved report), then `done` (its id); any refusal reaches `error` with
 *  the server's message (e.g. a stale gate: "Confirm again"), never a blank report. */
export async function streamStackGenerate(
	token: string | null, body: StackGenerateBody,
	on: { candidate: (c: Record<string, unknown>) => void; done: (d: { report_id: string; description?: string }) => void; error: (m: string) => void },
	signal?: AbortSignal
): Promise<void> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const r = await fetch(`${API_URL}/api/canvas/stack/generate`, { method: 'POST', signal, headers, body: JSON.stringify(body) });
	if (!r.ok) return on.error(r.status === 404 ? STACK_SWITCHED_OFF : GENERATE_FAILED);
	await readSSEStream(r, (event, data) => {
		if (event === 'candidate') on.candidate(data);
		else if (event === 'done') on.done(data);
		else if (event === 'error') on.error(String(data?.message ?? GENERATE_FAILED));
	}, { signal });
}

/** After Generate: link the report to the stack session (only the id; everything else is already logged). */
export const postReportId = (token: string | null, session_id: string, report_id: string) =>
	post<{ ok: boolean }>(token, 'log', { session_id, report_id }, true);
