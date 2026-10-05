// Rail chat (spec §12.5, plan Task D2): the report chat call, the open items it sends, and the local `lane: chat`
// item an applied chat edit becomes. The chat endpoint does not persist messages (report_chat_messages is unused),
// so the thread and its chat items live for the session and are never posted to the review events route.
import { get } from 'svelte/store';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import type { ReviewItem } from './types';

/** One edit in the chat reply: verified edits get Apply; the rest show `failed` (verifier guard codes). */
export interface ChatEdit {
	section: string;
	find: string;
	replace: string;
	verified: boolean;
	failed: string[];
}

export interface ChatSource {
	url?: string;
	title?: string;
	[key: string]: unknown;
}

export interface ChatReply {
	response: string;
	edits: ChatEdit[];
	sources: ChatSource[];
}

export interface ChatOpenItem {
	id: string;
	section: string;
	kind: string;
	label: string;
}

export interface ChatHistoryEntry {
	role: 'user' | 'assistant';
	content: string;
}

export interface ChatRequest {
	message: string;
	history: ChatHistoryEntry[];
	/** The live editor document: the backend checks edits against it. */
	text: string;
	openItems: ChatOpenItem[];
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

function normEdit(e: Record<string, unknown>): ChatEdit {
	return {
		section: str(e.section),
		find: str(e.find),
		replace: str(e.replace),
		verified: e.verified === true,
		failed: Array.isArray(e.failed) ? e.failed.map(String) : []
	};
}

export async function sendChat(reportId: string, req: ChatRequest): Promise<ChatReply> {
	const res = await fetch(`${API_URL}/api/reports/${encodeURIComponent(reportId)}/chat`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${get(token)}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({
			message: req.message,
			history: req.history,
			text: req.text,
			open_items: req.openItems
		})
	});
	let data: Record<string, unknown> | null = null;
	try {
		data = await res.json();
	} catch {
		data = null;
	}
	if (!res.ok || !data || data.success !== true) {
		throw new Error(str(data?.error) || `chat request failed (${res.status})`);
	}
	const edits = Array.isArray(data.edits) ? (data.edits as Record<string, unknown>[]) : [];
	return {
		response: str(data.response),
		edits: edits.filter((e) => e && typeof e === 'object').map(normEdit),
		sources: Array.isArray(data.sources) ? (data.sources as ChatSource[]) : []
	};
}

const OPEN = new Set(['open', 'stale']);

/** What the rail still shows as open (so chat does not propose it again). */
export function compactOpenItems(items: readonly ReviewItem[]): ChatOpenItem[] {
	return items
		.filter(
			(i) => OPEN.has(i.status) && i.cls !== 'suppress' && i.kind !== 'assumed_normal' && i.lane !== 'chat'
		)
		.map((i) => ({ id: i.id, section: i.section ?? '', kind: i.kind, label: i.label }));
}

export const chatItemId = (messageId: string, index: number) => `chat:${messageId}:${index}`;

/** The local item an applied chat edit becomes (spec §12.5): lane chat, linked to its message. */
export function chatItem(
	reportId: string,
	messageId: string,
	index: number,
	edit: Pick<ChatEdit, 'section' | 'find' | 'replace'>
): ReviewItem {
	const section = edit.section || null;
	return {
		id: chatItemId(messageId, index),
		key: chatItemId(messageId, index),
		report_id: reportId,
		run_id: '',
		lane: 'chat',
		detectors: ['chat'],
		kind: 'chat_edit',
		cls: 'minor',
		section,
		anchor: null,
		label: edit.replace ? `Chat: “${edit.replace}”` : `Chat: remove “${edit.find}”`,
		reason: '',
		edit: { mode: 'replace', find: edit.find, replace: edit.replace, section },
		evidence: { message_id: messageId, edit_index: index },
		status: 'open',
		history: [],
		engine_version: 'chat'
	};
}

const FAILURES: Record<string, string> = {
	missing_find: 'No text to change was given',
	no_change: 'The edit changes nothing',
	anchor_not_unique: 'The text to change does not occur exactly once in the report',
	anchor_mid_sentence: 'The change starts or ends mid-sentence',
	ungrounded_number: 'It adds a number that is not in the dictation',
	ungrounded_side: 'It adds a side (left/right) that is not in the dictation',
	drops_negation: 'It drops a negation',
	drops_negative_item: 'It drops a stated negative',
	drops_sentence: 'It drops a whole sentence',
	remove_dictated: 'It removes dictated content',
	alters_dictated: 'It changes dictated content',
	removal_adds_content: 'A removal that also adds content',
	structure: 'It changes the report structure',
	outside_section: 'The text is not in the named section',
	duplicate: 'The text is already in the report'
};

export function failureText(code: string): string {
	return FAILURES[code] ?? code.replace(/_/g, ' ');
}
