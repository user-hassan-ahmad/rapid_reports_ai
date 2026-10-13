import { API_URL } from '$lib/config.js';
import type { ApplyResponse, DecideResponse, DecisionChange, LedgerEntry, SheetChecksResponse } from './types';

// The server's caps on /skill-sheet/decide (main.MAX_DECIDE_EXAMPLES, DECIDE_EXAMPLE_MAX_CHARS): the request is kept
// inside them so a long paste never turns the decision run into a refusal.
export const MAX_DECIDE_EXAMPLES = 5;
export const DECIDE_EXAMPLE_MAX_CHARS = 20_000;

async function post<T>(token: string | null, path: string, body: unknown): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/templates/skill-sheet/${path}`, {
		method: 'POST',
		headers,
		body: JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`skill-sheet ${path} ${res.status}`);
	return (await res.json()) as T;
}

export interface DecideRequest {
	scan_type: string;
	examples: { label?: string | null; content: string }[];
	template_id?: string | null;
	/** the study setup, read first by the decision run (the server truncates it, never refuses it) */
	template_name?: string;
	protocol_notes?: string;
}

export const postDecide = (token: string | null, body: DecideRequest) =>
	post<DecideResponse>(token, 'decide', {
		...body,
		examples: body.examples
			.slice(0, MAX_DECIDE_EXAMPLES)
			.map((e) => ({ ...e, content: e.content.slice(0, DECIDE_EXAMPLE_MAX_CHARS) }))
	});

export const postApplyDecisions = (
	token: string | null,
	body: { skill_sheet: string; decisions: LedgerEntry[]; changes: DecisionChange[]; source: 'creation' | 'first_use_review' | 'chat' }
) => post<ApplyResponse>(token, 'apply-decisions', body);

const CHECK_PARTS = ['fixed_cards', 'duplicate_cards', 'normal_report', 'uncovered_cards', 'unmatched_cards', 'stale_quotes', 'errors'] as const;

/** The Style step's checks; a part the server left out is an empty list (fail-soft, as a failed part). */
export async function postSheetChecks(
	token: string | null,
	body: { skill_sheet: string; decisions: LedgerEntry[] }
): Promise<SheetChecksResponse> {
	const r = await post<Partial<SheetChecksResponse> & { success: boolean }>(token, 'sheet-checks', body);
	const out = { ...r } as Record<string, unknown>;
	for (const k of CHECK_PARTS) if (!Array.isArray(out[k])) out[k] = [];
	return out as unknown as SheetChecksResponse;
}
