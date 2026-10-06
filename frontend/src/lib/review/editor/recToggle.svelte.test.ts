// Regression: the recommendation checkboxes must keep working across many untick (remove) / re-tick (undo) cycles,
// in any order across neighbouring recommendations, with the real command, field, decorations and store loop the
// viewer runs (ReportResponseViewer.executeCommand / postEvents), including store reloads between toggles.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import type { ReviewItem } from '../types';

vi.mock('../api', () => ({ getReview: vi.fn(), postEvent: vi.fn(), rerun: vi.fn() }));
import * as api from '../api';
import { createReviewStore } from '../store';
import { runCommand, type CommandName } from '../commands';
import { commandTransaction, fromItems, syncItems, widgetPosOf } from './field';
import { reviewExtensions } from './index';

// SYNTHETIC report: two recommendation clauses on one impression line (as the provenance pass emits them), and
// signature lines after the impression.
const A = 'CT thorax is recommended for staging;';
const B = 'EUS sampling is advised.';
const DOC = `FINDINGS:\nThe pancreas has a mass.\n\nIMPRESSION:\nPancreatic mass. ${A} ${B}\n\nDr A Person\nGMC 0000000`;

function recItem(id: string, text: string): ReviewItem {
	const start = DOC.indexOf(text);
	return {
		id,
		key: id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'additions',
		detectors: ['code.recommendation'],
		kind: 'recommendation',
		cls: 'minor',
		section: 'IMPRESSION',
		anchor: { start, end: start + text.length, text },
		label: 'Recommendation not dictated',
		reason: '',
		edit: { mode: 'remove', find: text, section: 'IMPRESSION' },
		status: 'open',
		history: [],
		engine_version: 'test'
	};
}

const STATUS: Record<string, ReviewItem['status']> = { edit: 'applied', apply: 'applied', undo: 'open' };

const views: EditorView[] = [];
afterEach(() => {
	for (const v of views.splice(0)) {
		v.dom.remove();
		v.destroy();
	}
	vi.mocked(api.postEvent).mockReset();
	vi.mocked(api.getReview).mockReset();
});

/** The viewer's loop: a command → one transaction → events posted through the store → the store's items synced
 * back into the field. The fake backend appends history like review_engine/store.append_event. */
async function setup() {
	const server = new Map<string, ReviewItem>([
		['ra', recItem('ra', A)],
		['rb', recItem('rb', B)]
	]);
	vi.mocked(api.getReview).mockImplementation(async () => ({
		success: true,
		mode: 'live',
		rail: true,
		run: null,
		lanes: {},
		items: [...server.values()].map((i) => structuredClone(i))
	}));
	vi.mocked(api.postEvent).mockImplementation(async (_r, id, command, textHash, detail) => {
		const cur = server.get(id)!;
		const next: ReviewItem = {
			...cur,
			status: STATUS[command] ?? cur.status,
			history: [...cur.history, { event: command, actor: 'user', text_hash: textHash, detail: detail ?? {} }]
		};
		server.set(id, next);
		await new Promise((r) => setTimeout(r, 5));
		return structuredClone(next);
	});
	const store = createReviewStore('rep1', { retryDelayMs: 1, maxRetries: 0 });
	await store.load();
	let view!: EditorView;
	const sync = () => view.dispatch(syncItems(view.state, get(store).items));
	const onCommand = (name: CommandName, itemId: string) => {
		const items = get(store).items;
		const item = items.find((i) => i.id === itemId) ?? null;
		const result = runCommand(name, {
			doc: view.state.doc.toString(),
			items,
			item,
			widgetPos: widgetPosOf(view.state)
		});
		if (result.error) return;
		view.dispatch(commandTransaction(view.state, result, items));
		const ev = result.event!;
		void Promise.resolve().then(() =>
			store.setStatus(ev.itemId, result.statuses?.[ev.itemId] ?? 'open', { command: ev.command, detail: ev.detail })
		);
	};
	const state = EditorState.create({
		doc: DOC,
		extensions: reviewExtensions({
			onCommand,
			getItem: (id) => get(store).items.find((i) => i.id === id),
			initial: fromItems(DOC, get(store).items).items
		})
	});
	const parent = document.createElement('div');
	document.body.append(parent);
	view = new EditorView({ state, parent });
	views.push(view);
	let last = get(store).items;
	store.subscribe((s) => {
		if (s.items === last) return;
		last = s.items;
		queueMicrotask(sync);
	});
	return { view, store };
}

const settle = () => new Promise((r) => setTimeout(r, 40));
const box = (view: EditorView, id: string) =>
	view.dom.querySelector<HTMLInputElement>(`[data-rv-suggestion="${id}"] input`)!;

describe('recommendation checkboxes', () => {
	it('the reported sequence: untick one, untick its neighbour, re-tick the first, re-tick the second, again', async () => {
		const { view } = await setup();
		for (let cycle = 0; cycle < 3; cycle++) {
			for (const [id, ticked] of [
				['ra', false],
				['rb', false],
				['ra', true],
				['rb', true]
			] as const) {
				box(view, id).click();
				await settle();
				expect(box(view, id).checked, `cycle ${cycle}: ${id} → ${ticked}`).toBe(ticked);
				const text = id === 'ra' ? 'CT thorax is recommended for staging' : 'EUS sampling is advised';
				expect(view.state.doc.toString().includes(text), `cycle ${cycle}: ${id} text`).toBe(ticked);
			}
			expect(view.state.doc.toString()).toBe(DOC);
		}
	});

	it('the same recommendation, many cycles, with store reloads (save / probe) in between', async () => {
		const { view, store } = await setup();
		for (let cycle = 0; cycle < 4; cycle++) {
			box(view, 'rb').click();
			await settle();
			await store.load();
			await settle();
			expect(view.state.doc.toString()).not.toContain(B);
			expect(box(view, 'rb').checked).toBe(false);
			box(view, 'rb').click();
			await settle();
			await store.load();
			await settle();
			expect(view.state.doc.toString()).toBe(DOC);
			expect(box(view, 'rb').checked).toBe(true);
		}
	});

	it('a command that cannot run leaves the box showing the report (never the click)', async () => {
		// the host refuses every command (as the viewer does when a command returns an error)
		const items = [recItem('ra', A), recItem('rb', B)];
		const onCommand = vi.fn();
		const view = new EditorView({
			state: EditorState.create({
				doc: DOC,
				extensions: reviewExtensions({ onCommand, initial: fromItems(DOC, items).items })
			}),
			parent: document.body.appendChild(document.createElement('div'))
		});
		views.push(view);
		for (let k = 0; k < 3; k++) {
			box(view, 'ra').click();
			expect(box(view, 'ra').checked).toBe(true);
		}
		expect(onCommand.mock.calls.map((c) => c[0])).toEqual(['remove', 'remove', 'remove']);
	});
});
