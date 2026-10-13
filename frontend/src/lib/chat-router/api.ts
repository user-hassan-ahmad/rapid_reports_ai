import { API_URL } from '$lib/config.js';
import type { LedgerEntry } from '$lib/template-rules/types';
import type { CardAnswer, RouterRecord, RouterTurnResponse } from './types';

async function post(token: string | null, path: 'undo' | 'card', body: unknown): Promise<RouterTurnResponse> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/templates/skill-sheet/refine/${path}`, {
		method: 'POST',
		headers,
		body: JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`refine ${path} ${res.status}`);
	return (await res.json()) as RouterTurnResponse;
}

export const postRouterUndo = (
	token: string | null,
	body: {
		skill_sheet: string;
		decisions: LedgerEntry[];
		changes: RouterRecord[];
		changes_sig?: string | null;
		turn_id?: string | null;
		template_id?: string | null;
	}
) => post(token, 'undo', body);

export const postRouterCard = (
	token: string | null,
	body: { skill_sheet: string; decisions: LedgerEntry[]; answer: CardAnswer; template_id?: string | null }
) => post(token, 'card', body);
