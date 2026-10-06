// Rail chat (spec §12.5, plan Task D2): the report chat call, the open items it sends, and the local `lane: chat`
// item an applied chat edit becomes. The backend saves each turn in report_chat_messages (spec §10.2, §12.6):
// `loadThread` restores it when a report opens (History included; nothing re-runs) and `markApplied` records
// Apply / Undo of an edit, so applied edits are rebuilt as `lane: chat` items (`appliedChatItems`). Chat items stay
// out of the review events route: the review engine knows its own items only.
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
	/** The apply event detail saved with the edit (from/insert/removed/left/right): Undo after a reload. */
	appliedDetail?: Record<string, unknown>;
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
	/** The saved message ids (null: the turn was not saved). */
	userMessageId: string | null;
	messageId: string | null;
}

/** One saved thread message (GET /api/reports/{id}/chat). */
export interface ChatThreadMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	edits: ChatEdit[];
	/** The `lane: chat` item ids of the edits applied from this message. */
	appliedItemIds: string[];
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
		failed: Array.isArray(e.failed) ? e.failed.map(String) : [],
		...(e.applied_detail && typeof e.applied_detail === 'object'
			? { appliedDetail: e.applied_detail as Record<string, unknown> }
			: {})
	};
}

const reportPath = (reportId: string) => `${API_URL}/api/reports/${encodeURIComponent(reportId)}/chat`;

async function readJson(res: Response): Promise<Record<string, unknown>> {
	let data: Record<string, unknown> | null = null;
	try {
		data = await res.json();
	} catch {
		data = null;
	}
	if (!res.ok || !data || data.success !== true) {
		throw new Error(str(data?.error) || `chat request failed (${res.status})`);
	}
	return data;
}

const strOrNull = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

export async function sendChat(reportId: string, req: ChatRequest): Promise<ChatReply> {
	const res = await fetch(reportPath(reportId), {
		method: 'POST',
		headers: { Authorization: `Bearer ${get(token)}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({
			message: req.message,
			history: req.history,
			text: req.text,
			open_items: req.openItems
		})
	});
	const data = await readJson(res);
	const edits = Array.isArray(data.edits) ? (data.edits as Record<string, unknown>[]) : [];
	return {
		response: str(data.response),
		edits: edits.filter((e) => e && typeof e === 'object').map(normEdit),
		sources: Array.isArray(data.sources) ? (data.sources as ChatSource[]) : [],
		userMessageId: strOrNull(data.user_message_id),
		messageId: strOrNull(data.message_id)
	};
}

/** The saved thread, oldest first. */
export async function loadThread(reportId: string): Promise<ChatThreadMessage[]> {
	const res = await fetch(reportPath(reportId), { headers: { Authorization: `Bearer ${get(token)}` } });
	const data = await readJson(res);
	const rows = Array.isArray(data.messages) ? (data.messages as Record<string, unknown>[]) : [];
	return rows
		.filter((m) => m && typeof m === 'object' && typeof m.id === 'string')
		.map((m) => ({
			id: m.id as string,
			role: m.role === 'user' ? ('user' as const) : ('assistant' as const),
			content: str(m.content),
			edits: (Array.isArray(m.edits) ? (m.edits as Record<string, unknown>[]) : [])
				.filter((e) => e && typeof e === 'object')
				.map(normEdit),
			appliedItemIds: Array.isArray(m.applied_item_ids) ? m.applied_item_ids.map(String) : [],
			sources: []
		}));
}

/** Record Apply (applied) or Undo of one edit; returns the message's applied item ids. */
export async function markApplied(
	reportId: string,
	messageId: string,
	editIndex: number,
	itemId: string,
	applied: boolean,
	detail?: Record<string, unknown>
): Promise<string[]> {
	const res = await fetch(`${reportPath(reportId)}/${encodeURIComponent(messageId)}/applied`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${get(token)}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({
			edit_index: editIndex,
			item_id: itemId,
			applied,
			...(detail ? { detail } : {})
		})
	});
	const data = await readJson(res);
	return Array.isArray(data.applied_item_ids) ? data.applied_item_ids.map(String) : [];
}

/** Ids the thread makes up for a message with no saved id (an error, or a turn the backend did not save). */
export const isLocalMessage = (messageId: string) => messageId.startsWith('local-');

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

/** The applied edits of a saved thread as applied `lane: chat` items (spec §12.6: reopen restores applied state).
 * Their history holds the saved apply detail (else the edit's own text), so Undo can find the text again. */
export function appliedChatItems(reportId: string, thread: readonly ChatThreadMessage[]): ReviewItem[] {
	const out: ReviewItem[] = [];
	for (const m of thread) {
		m.edits.forEach((e, k) => {
			const id = chatItemId(m.id, k);
			if (!m.appliedItemIds.includes(id)) return;
			const detail = e.appliedDetail ?? { insert: e.replace, removed: e.find };
			out.push({
				...chatItem(reportId, m.id, k, e),
				status: 'applied',
				history: [{ event: 'apply', actor: 'user', text_hash: null, detail }]
			});
		});
	}
	return out;
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

/** What the rail needs to host the chat (absent: no composer, e.g. the dev page). */
export interface RailChat {
	reportId: string;
	/** The live editor document. */
	getText: () => string;
	/** Apply a verified edit as a local chat item through the apply command; null on success, else why not. */
	applyEdit: (messageId: string, index: number, edit: ChatEdit) => string | null;
	/** The saved thread the rail opens with (History / reload). */
	thread?: ChatThreadMessage[];
}
