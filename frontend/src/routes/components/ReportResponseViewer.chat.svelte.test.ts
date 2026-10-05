// Rail chat and the viewer follow-ups (Plan 3 D2): chat edits apply through the command path as local chat items,
// "Ask in chat" fills the rail composer, Discard posts undo for what was applied since the last save, and the rail
// groups follow the report's headings. SYNTHETIC report and items only; the review, chat and workspace calls are
// mocked, every other fetch answers "not found".
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { EditorView } from '@codemirror/view';
import type { ReviewItem, ReviewResponse } from '$lib/review/types';

const getReview = vi.fn();
const postEvent = vi.fn();
const probe = vi.fn(async (_r: string, _t: string, hash: string) => ({
	success: true,
	text_hash: hash,
	addressed: [],
	reprepare: [],
	new_items: []
}));
vi.mock('$lib/review/api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: (...a: unknown[]) => postEvent(...a),
	rerun: vi.fn(async () => ({ success: true, status: 'running' })),
	probe: (...a: [string, string, string]) => probe(...a),
	reprepare: vi.fn(async () => ({ success: true, text_hash: '', items: [] }))
}));
vi.mock('$lib/review/workspace', () => ({
	loadWorkspace: vi.fn(async () => null),
	saveWorkspace: vi.fn(async (_r: string, s: unknown) => s),
	createWorkspaceSaver: () => ({ schedule: vi.fn(), flush: vi.fn(async () => {}), cancel: vi.fn() })
}));
const sendChat = vi.fn();
const loadThread = vi.fn();
const markApplied = vi.fn();
vi.mock('$lib/review/chat', async (orig) => ({
	...(await orig<typeof import('$lib/review/chat')>()),
	sendChat: (...a: unknown[]) => sendChat(...a),
	loadThread: (...a: unknown[]) => loadThread(...a),
	markApplied: (...a: unknown[]) => markApplied(...a)
}));

const { default: ReportResponseViewer } = await import('./ReportResponseViewer.svelte');

const REPORT = `FINDINGS:
The spleen measures 9 cm. No ascites.

IMPRESSION:
Normal study.`;

const STATUS: Record<string, ReviewItem['status']> = {
	apply: 'applied',
	edit: 'applied',
	undo: 'open',
	dismiss: 'dismissed',
	restore: 'open'
};

function action(over: Partial<ReviewItem> = {}): ReviewItem {
	const start = REPORT.indexOf('9 cm');
	return {
		id: 'a1',
		key: 'a1',
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'accuracy',
		detectors: [],
		kind: 'measurement',
		cls: 'action',
		section: 'FINDINGS',
		anchor: { start, end: start + 4, text: '9 cm' },
		label: 'Measurement differs',
		reason: 'The dictation gives 11 cm.',
		edit: { mode: 'replace', find: '9 cm', replace: '11 cm' },
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

function review(items: ReviewItem[]): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
	return {
		success: true,
		mode: 'live',
		rail: true,
		run: {
			id: 'run1',
			mode: 'live',
			engine_version: 'test',
			pathway: 'quick',
			lanes,
			timings_ms: {},
			cost: {},
			errors: {},
			created_at: null
		},
		lanes,
		items
	};
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const viewOf = (root: HTMLElement) => EditorView.findFromDOM(root.querySelector('.cm-editor') as HTMLElement)!;

beforeEach(async () => {
	await page.viewport(1400, 900);
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => new Response(JSON.stringify({ success: false }), { status: 404 }))
	);
	postEvent.mockImplementation(
		async (_r: string, id: string, command: string, _h: unknown, detail?: Record<string, unknown>) => ({
			...action(),
			id,
			// the backend reinstates an engine pre-apply on Discard (store._reinstates_pre_apply)
			status: (detail?.reinstate as ReviewItem['status']) ?? STATUS[command] ?? 'open'
		})
	);
	loadThread.mockResolvedValue([]);
	markApplied.mockResolvedValue([]);
});

afterEach(() => {
	vi.unstubAllGlobals();
	getReview.mockReset();
	postEvent.mockReset();
	sendChat.mockReset();
	loadThread.mockReset();
	markApplied.mockReset();
	probe.mockClear();
});

async function mount(items: ReviewItem[] = [action()]) {
	getReview.mockResolvedValue(review(items));
	const save = vi.fn();
	const screen = render(ReportResponseViewer, {
		props: { visible: true, response: REPORT, reportId: 'rep1' },
		events: { save }
	} as Parameters<typeof render<typeof ReportResponseViewer>>[1]);
	await pause(400);
	return { ...screen, save };
}

async function ask(text: string) {
	await page.getByRole('textbox', { name: 'Chat message' }).fill(text);
	await page.getByRole('button', { name: 'Send' }).click();
}

describe('rail chat in the report viewer', () => {
	it('sends the live document and open items; Apply changes the editor, posts nothing, triggers the probe', async () => {
		sendChat.mockResolvedValue({
			response: 'One edit.',
			edits: [{ section: 'FINDINGS', find: 'No ascites.', replace: 'Small volume ascites.', verified: true, failed: [] }],
			sources: []
		});
		const { container, save } = await mount();
		const view = viewOf(container);
		view.dispatch({ changes: { from: view.state.doc.length, insert: ' Edited.' } });
		await ask('Mention the ascites');
		await expect.element(page.getByText('One edit.')).toBeInTheDocument();
		const req = sendChat.mock.calls[0][1] as Record<string, unknown>;
		expect(req.text).toBe(REPORT + ' Edited.');
		expect(req.openItems).toEqual([
			{ id: 'a1', section: 'FINDINGS', kind: 'measurement', label: 'Measurement differs' }
		]);

		probe.mockClear();
		await page.getByRole('button', { name: 'Apply chat edit: Small volume ascites.' }).click();
		await pause(300);
		expect(view.state.doc.toString()).toContain('9 cm. Small volume ascites.');
		await expect.element(page.getByText('Applied')).toBeInTheDocument();
		await expect.element(page.getByText('Unsaved changes')).toBeInTheDocument();
		expect(postEvent).not.toHaveBeenCalled();
		await expect.poll(() => probe.mock.calls.length, { timeout: 3000 }).toBeGreaterThan(0);

		// the chat item is local: finalise sends engine items only
		await page.getByRole('button', { name: 'Save Changes' }).click();
		expect(save.mock.calls[0][0].detail.reviewAppliedItemIds).toEqual([]);
	});

	it('a failed edit shows its reasons and no Apply', async () => {
		sendChat.mockResolvedValue({
			response: 'Tried.',
			edits: [{ section: 'FINDINGS', find: 'spleen', replace: 'spleen 14 cm', verified: false, failed: ['ungrounded_number'] }],
			sources: []
		});
		await mount();
		await ask('Size?');
		await expect.element(page.getByText('It adds a number that is not in the dictation')).toBeInTheDocument();
		expect(page.getByRole('button', { name: /^Apply chat edit/ }).elements()).toHaveLength(0);
	});

	it('"Ask in chat" on an item pre-fills the rail composer and posts ask_chat', async () => {
		const openSidebar = vi.fn();
		getReview.mockResolvedValue(review([action({ edit: null })]));
		render(ReportResponseViewer, {
			props: { visible: true, response: REPORT, reportId: 'rep1' },
			events: { openSidebar }
		} as Parameters<typeof render<typeof ReportResponseViewer>>[1]);
		await pause(400);
		await page.getByRole('button', { name: 'Ask in chat: Measurement differs' }).click();
		await expect
			.element(page.getByRole('textbox', { name: 'Chat message' }))
			.toHaveValue('Measurement differs: The dictation gives 11 cm.\n\nOn: "9 cm"');
		expect(openSidebar).not.toHaveBeenCalled();
		await expect.poll(() => postEvent.mock.calls.map((c) => c[2])).toEqual(['ask_chat']);
	});
});

describe('chat persistence (spec §10.2, §12.6)', () => {
	const EDIT = { section: 'FINDINGS', find: 'No ascites.', replace: 'Small volume ascites.', verified: true, failed: [] };
	const UID = '00000000-0000-4000-8000-0000000000a1';
	const AID = '00000000-0000-4000-8000-0000000000a2';

	it('a sent turn keeps its saved ids: Apply and Undo record applied state on the message', async () => {
		sendChat.mockResolvedValue({ response: 'One edit.', edits: [EDIT], sources: [], userMessageId: UID, messageId: AID });
		const { container } = await mount();
		await ask('Mention the ascites');
		await page.getByRole('button', { name: 'Apply chat edit: Small volume ascites.' }).click();
		await expect.poll(() => markApplied.mock.calls.length).toBe(1);
		const [rid, mid, idx, itemId, applied, detail] = markApplied.mock.calls[0];
		expect([rid, mid, idx, itemId, applied]).toEqual(['rep1', AID, 0, `chat:${AID}:0`, true]);
		expect(detail).toMatchObject({ insert: 'Small volume ascites.', removed: 'No ascites.' });
		await page.getByRole('button', { name: 'Undo' }).click();
		await expect.poll(() => markApplied.mock.calls.length).toBe(2);
		expect(markApplied.mock.calls[1].slice(0, 5)).toEqual(['rep1', AID, 0, `chat:${AID}:0`, false]);
		expect(viewOf(container).state.doc.toString()).toBe(REPORT);
	});

	it('the saved thread survives a reload: the viewer loads it on open and the rail shows it', async () => {
		loadThread.mockResolvedValue([
			{ id: UID, role: 'user', content: 'Mention the ascites', edits: [], appliedItemIds: [], sources: [] },
			{ id: AID, role: 'assistant', content: 'One edit.', edits: [EDIT], appliedItemIds: [], sources: [] }
		]);
		await mount();
		expect(loadThread).toHaveBeenCalledWith('rep1');
		await page.getByRole('button', { name: 'Chat', exact: true }).click();
		await expect.element(page.getByText('Mention the ascites')).toBeInTheDocument();
		await expect.element(page.getByText('One edit.')).toBeInTheDocument();
		await expect
			.element(page.getByRole('button', { name: 'Apply chat edit: Small volume ascites.' }))
			.toBeInTheDocument();
		// the next turn carries the saved thread as history
		sendChat.mockResolvedValue({ response: 'Ok.', edits: [], sources: [], userMessageId: null, messageId: null });
		await ask('Thanks');
		expect((sendChat.mock.calls[0][1] as { history: unknown }).history).toEqual([
			{ role: 'user', content: 'Mention the ascites' },
			{ role: 'assistant', content: 'One edit.' }
		]);
	});

	it('reopen restores applied state: "✓ Applied · Undo", and Undo reverts the text and records it', async () => {
		const saved = REPORT.replace('No ascites.', 'Small volume ascites.');
		const at = REPORT.indexOf('No ascites.');
		loadThread.mockResolvedValue([
			{ id: UID, role: 'user', content: 'Mention the ascites', edits: [], appliedItemIds: [], sources: [] },
			{
				id: AID,
				role: 'assistant',
				content: 'One edit.',
				edits: [{ ...EDIT, appliedDetail: { from: at, insert: 'Small volume ascites.', removed: 'No ascites.', left: REPORT.slice(at - 16, at), right: REPORT.slice(at + 11, at + 27) } }],
				appliedItemIds: [`chat:${AID}:0`],
				sources: []
			}
		]);
		getReview.mockResolvedValue(review([action()]));
		const screen = render(ReportResponseViewer, {
			props: { visible: true, response: saved, reportId: 'rep1' }
		} as Parameters<typeof render<typeof ReportResponseViewer>>[1]);
		await pause(400);
		await page.getByRole('button', { name: 'Chat', exact: true }).click();
		await expect.element(page.getByText('Applied')).toBeInTheDocument();
		expect(page.getByRole('button', { name: /^Apply chat edit/ }).elements()).toHaveLength(0);
		await page.getByRole('button', { name: 'Undo' }).click();
		await pause(200);
		expect(viewOf(screen.container).state.doc.toString()).toBe(REPORT);
		await expect.poll(() => markApplied.mock.calls.length).toBe(1);
		expect(markApplied.mock.calls[0].slice(0, 5)).toEqual(['rep1', AID, 0, `chat:${AID}:0`, false]);
		expect(postEvent).not.toHaveBeenCalled();
	});
});

describe('Discard after Apply', () => {
	it('posts undo for each item applied since the last save and restores the text', async () => {
		const { container } = await mount();
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(200);
		const view = viewOf(container);
		expect(view.state.doc.toString()).toContain('11 cm');
		await page.getByRole('button', { name: 'Discard' }).click();
		await pause(300);
		expect(view.state.doc.toString()).toBe(REPORT);
		expect(postEvent.mock.calls.map((c) => [c[1], c[2]])).toEqual([
			['a1', 'apply'],
			['a1', 'undo']
		]);
		expect(postEvent.mock.calls[1][4]).toMatchObject({ via: 'discard' });
	});

	/** live.rebase_items' evidence.undo for the span [j1, j2) of the written text. */
	function undoOf(written: string, j1: number, j2: number, original_text: string) {
		return {
			final_span: [j1, j2] as [number, number],
			original_text,
			final_text: written.slice(j1, j2),
			left: written.slice(Math.max(0, j1 - 16), j1),
			right: written.slice(j2, j2 + 16)
		};
	}
	const engineHistory = [{ event: 'pre_applied', actor: 'post_check', text_hash: null, detail: {} }];
	/** The backend answers with the item itself at its new status. */
	function serve(it: ReviewItem) {
		postEvent.mockImplementation(
			async (_r: string, _id: string, command: string, _h: unknown, detail?: Record<string, unknown>) => ({
				...it,
				status: (detail?.reinstate as ReviewItem['status']) ?? STATUS[command] ?? 'open'
			})
		);
	}

	it('an engine pre-applied insert undone since the save returns to pre_applied (apply, via discard)', async () => {
		const j1 = REPORT.indexOf(' No ascites.');
		const pre = action({
			id: 'p1',
			lane: 'coverage',
			kind: 'omission',
			cls: 'minor',
			status: 'pre_applied',
			label: 'Ascites statement',
			edit: { mode: 'insert', after: null, section: 'FINDINGS', replace: 'No ascites.' },
			anchor: { start: j1 + 1, end: j1 + 12, text: 'No ascites.' },
			evidence: { undo: undoOf(REPORT, j1, j1 + 12, '') },
			history: engineHistory
		});
		serve(pre);
		const { container } = await mount([pre]);
		const view = viewOf(container);
		await page.getByRole('button', { name: 'Undo: Ascites statement' }).click();
		await pause(200);
		expect(view.state.doc.toString()).not.toContain('No ascites.');
		await page.getByRole('button', { name: 'Discard' }).click();
		await pause(300);
		expect(view.state.doc.toString()).toBe(REPORT);
		expect(postEvent.mock.calls.map((c) => [c[1], c[2]])).toEqual([
			['p1', 'undo'],
			['p1', 'apply']
		]);
		expect(postEvent.mock.calls[1][4]).toEqual({ via: 'discard', reinstate: 'pre_applied' });
		await expect.element(page.getByText('added from your dictation')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Undo: Ascites statement' })).toBeInTheDocument();
	});

	it('an engine removal restored since the save is removed again (apply, via discard)', async () => {
		const i = REPORT.indexOf('No ascites.');
		const removal = action({
			id: 'r1',
			kind: 'removed',
			cls: 'action',
			status: 'pre_applied',
			label: 'Trace fluid removed',
			edit: { mode: 'remove', find: 'Trace fluid.' },
			anchor: { start: i, end: i, text: '' },
			evidence: { removed_text: 'Trace fluid.', undo: undoOf(REPORT, i, i, 'Trace fluid. ') },
			history: engineHistory
		});
		serve(removal);
		const { container } = await mount([removal]);
		const view = viewOf(container);
		await page.getByRole('button', { name: 'Restore: Trace fluid removed' }).click();
		await pause(200);
		expect(view.state.doc.toString()).toContain('9 cm. Trace fluid. No ascites.');
		await page.getByRole('button', { name: 'Discard' }).click();
		await pause(300);
		expect(view.state.doc.toString()).toBe(REPORT);
		expect(postEvent.mock.calls.map((c) => [c[1], c[2]])).toEqual([
			['r1', 'restore'],
			['r1', 'apply']
		]);
		expect(postEvent.mock.calls[1][4]).toEqual({ via: 'discard', reinstate: 'pre_applied' });
		await expect.element(page.getByRole('button', { name: 'Restore: Trace fluid removed' })).toBeInTheDocument();
	});

	it('an apply saved, then undone, is applied again on Discard', async () => {
		const { rerender, container } = await mount();
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(100);
		await page.getByRole('button', { name: 'Save Changes' }).click();
		const saved = REPORT.replace('9 cm', '11 cm');
		const at = REPORT.indexOf('9 cm');
		const detail = { from: at, insert: '11 cm', removed: '9 cm', left: REPORT.slice(at - 16, at), right: REPORT.slice(at + 4, at + 20) };
		// the reload after the save serves the item as applied (the backend recorded the apply)
		getReview.mockResolvedValue(
			review([action({ status: 'applied', history: [{ event: 'apply', actor: 'user', text_hash: null, detail }] })])
		);
		await rerender({ response: saved });
		await pause(300);
		await page.getByRole('button', { name: 'Undo: Measurement differs' }).click();
		await pause(200);
		await page.getByRole('button', { name: 'Discard' }).click();
		await pause(300);
		expect(viewOf(container).state.doc.toString()).toBe(saved);
		expect(postEvent.mock.calls.map((c) => [c[2], c[4]?.via])).toEqual([
			['apply', undefined],
			['undo', undefined],
			['apply', 'discard']
		]);
		expect(postEvent.mock.calls[2][4]).toEqual({ via: 'discard' });
	});

	it('posts nothing for an apply already saved', async () => {
		const { rerender } = await mount();
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(100);
		await page.getByRole('button', { name: 'Save Changes' }).click();
		await rerender({ response: REPORT.replace('9 cm', '11 cm') });
		await pause(300);
		expect(page.getByRole('button', { name: 'Discard' }).elements()).toHaveLength(0);
		expect(postEvent.mock.calls.map((c) => c[2])).toEqual(['apply']);
	});
});

describe('rail section order', () => {
	it('follows the report headings when no section list is passed (case-insensitive)', async () => {
		const imp = REPORT.indexOf('Normal study.');
		const items = [
			// anchored after FINDINGS but listed first, with a lowercased section name
			action({
				id: 'b1',
				section: 'impression',
				label: 'Impression item',
				anchor: { start: imp, end: imp + 6, text: 'Normal' },
				edit: null
			}),
			// no anchor: without an order this group would sort last
			action({ id: 'a2', section: 'FINDINGS', label: 'Findings item', anchor: null, edit: null })
		];
		await mount(items);
		const headings = [...document.querySelectorAll('[data-rv-section]')].map((h) =>
			h.getAttribute('data-rv-section')
		);
		expect(headings).toEqual(['FINDINGS', 'impression']);
	});
});
