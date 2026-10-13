// Copilot API client: the only place the frontend calls /api/canvas/stack/guidelines/*.
// Fail open: every call has a timeout; callers drop stale answers and treat CopilotOff as "off for this page".
import { get } from 'svelte/store';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import type { CalculateBody, CalculateResult, MatchBody, MatchResult, OpenBody, OpenResult } from './types';

/** The server's _require() answered 404 with detail OFF_DETAIL: the Copilot is off; send nothing more this page.
 *  Any other 404 (unknown route, proxy, mid-deploy) is a card-local CopilotError; /settings/status stays the
 *  authoritative off signal. */
export class CopilotOff extends Error {
	constructor() {
		super('copilot off');
		this.name = 'CopilotOff';
	}
}

export class CopilotError extends Error {
	constructor(
		readonly reason: 'http' | 'timeout' | 'network',
		readonly status = 0
	) {
		super(`copilot request failed (${reason}${status ? ` ${status}` : ''})`);
		this.name = 'CopilotError';
	}
}

export const OFF_DETAIL = 'copilot_off';

async function isOff(res: Response): Promise<boolean> {
	try {
		return ((await res.json()) as { detail?: unknown })?.detail === OFF_DETAIL;
	} catch {
		return false;
	}
}

// Longer than the server's own budgets: OPEN_TIMEOUT_S 60 (its comment asks for >= 90), PREVIEW_TIMEOUT_S 25.
export const TIMEOUT_MS = { match: 45_000, other: 60_000, open: 90_000, preview: 35_000, calculate: 35_000 } as const;

// Mirror the server's caps (MatchRequest.findings, FindingIn.text, OpenRequest.answered) so a long case never 422s.
export const MAX_FINDINGS = 20;
export const MAX_FINDING_TEXT = 1000;
export const MAX_ANSWERED = 20;

async function post<T>(path: string, body: unknown, timeoutMs: number, signal?: AbortSignal): Promise<T> {
	const ac = new AbortController();
	let timedOut = false;
	const timer = setTimeout(() => {
		timedOut = true;
		ac.abort();
	}, timeoutMs);
	const onAbort = () => ac.abort();
	if (signal?.aborted) ac.abort();
	else signal?.addEventListener('abort', onAbort, { once: true });
	try {
		let res: Response;
		try {
			res = await fetch(`${API_URL}/api/canvas/stack/guidelines/${path}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${get(token)}` },
				body: JSON.stringify(body),
				signal: ac.signal
			});
		} catch (e) {
			if (timedOut) throw new CopilotError('timeout');
			if (signal?.aborted) throw e; // the caller superseded it: not a failure
			throw new CopilotError('network');
		}
		if (res.status === 404 && (await isOff(res))) throw new CopilotOff();
		if (!res.ok) throw new CopilotError('http', res.status);
		try {
			return (await res.json()) as T;
		} catch {
			if (timedOut) throw new CopilotError('timeout');
			if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
			throw new CopilotError('http', res.status);
		}
	} finally {
		clearTimeout(timer);
		signal?.removeEventListener('abort', onAbort);
	}
}

// Bodies are rebuilt key by key so nothing outside the wire contract is ever sent.
function matchBody(b: MatchBody): MatchBody {
	return {
		scan_type: b.scan_type,
		clinical_history: b.clinical_history,
		findings: b.findings.slice(0, MAX_FINDINGS).map((f) => ({ id: f.id, text: f.text.slice(0, MAX_FINDING_TEXT) })),
		dictation: b.dictation,
		patient: b.patient
	};
}

function openBody(b: OpenBody): OpenBody {
	const out: OpenBody = {
		card: b.card,
		finding: b.finding,
		findings: b.findings,
		clinical_history: b.clinical_history,
		answered: Object.fromEntries(Object.entries(b.answered).slice(0, MAX_ANSWERED)),
		patient: b.patient
	};
	if (b.lesion !== undefined) out.lesion = b.lesion;
	return out;
}

export const match = (b: MatchBody, signal?: AbortSignal) => post<MatchResult>('match', matchBody(b), TIMEOUT_MS.match, signal);
export const matchOther = (b: MatchBody, signal?: AbortSignal) =>
	post<MatchResult>('match/other', matchBody(b), TIMEOUT_MS.other, signal);
export const open = (b: OpenBody, signal?: AbortSignal) => post<OpenResult>('open', openBody(b), TIMEOUT_MS.open, signal);
export const preview = (b: OpenBody, signal?: AbortSignal) => post<OpenResult>('preview', openBody(b), TIMEOUT_MS.preview, signal);
/** Task 3. Until that route lands a call 404s as a card-local CopilotError (not CopilotOff). */
export const calculate = (b: CalculateBody, signal?: AbortSignal) =>
	post<CalculateResult>('calculate', { ...openBody(b), values: b.values }, TIMEOUT_MS.calculate, signal);
