// The review layer in the report viewer: the recommendation checkbox across many toggles, the inline unsaved status.
// SYNTHETIC report and items only; the review API and the workspace endpoints are mocked, every other fetch 404s.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { EditorView } from '@codemirror/view';
import type { ReviewItem, ReviewResponse } from '$lib/review/types';

const getReview = vi.fn();
const postEvent = vi.fn();
vi.mock('$lib/review/api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: (...a: unknown[]) => postEvent(...a),
	rerun: vi.fn(async () => ({ success: true, status: 'running' })),
	probe: vi.fn(async (_r: string, _t: string, hash: string) => ({
		success: true,
		text_hash: hash,
		addressed: [],
		reprepare: [],
		new_items: []
	})),
	reprepare: vi.fn(async () => ({ success: true, text_hash: '', items: [] }))
}));
vi.mock('$lib/review/workspace', () => ({
	loadWorkspace: vi.fn(async () => null),
	saveWorkspace: vi.fn(async (_r: string, s: unknown) => s),
	createWorkspaceSaver: () => ({ schedule: vi.fn(), flush: vi.fn(async () => {}), cancel: vi.fn() })
}));

const { default: ReportResponseViewer } = await import('./ReportResponseViewer.svelte');

const REC = 'Suggest surgical review.';
const REPORT = `FINDINGS:
The pancreas has a mass. No ascites.

IMPRESSION:
Pancreatic mass. ${REC}

Dr A Person
GMC 0000000`;

const STATUS: Record<string, ReviewItem['status']> = {
	apply: 'applied',
	edit: 'applied',
	undo: 'open',
	dismiss: 'dismissed',
	restore: 'open'
};

function rec(): ReviewItem {
	const start = REPORT.indexOf(REC);
	return {
		id: 'rec1',
		key: 'rec1',
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'additions',
		detectors: ['code.recommendation'],
		kind: 'recommendation',
		cls: 'minor',
		section: 'IMPRESSION',
		anchor: { start, end: start + REC.length, text: REC },
		label: 'Recommendation not dictated',
		reason: 'Added by the report writer; remove it if not wanted.',
		edit: { mode: 'remove', find: REC, section: 'IMPRESSION' },
		status: 'open',
		history: [],
		engine_version: 'test'
	};
}

/** A fake backend: items keep their history and status like review_engine/store.append_event. */
let server: Map<string, ReviewItem>;
function review(): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
	return {
		success: true,
		mode: 'live',
		rail: true,
		run: { id: 'run1', mode: 'live', engine_version: 'test', pathway: 'quick', lanes, timings_ms: {}, cost: {}, errors: {}, created_at: null },
		lanes,
		items: [...server.values()].map((i) => structuredClone(i))
	};
}

type MountOpts = Parameters<typeof render<typeof ReportResponseViewer>>[1];
const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const viewOf = (root: HTMLElement) => EditorView.findFromDOM(root.querySelector('.cm-editor') as HTMLElement)!;
const box = (root: HTMLElement) => root.querySelector<HTMLInputElement>('[data-rv-suggestion="rec1"] input')!;
/** A real pointer click (CDP), not a synthetic .click(): the editor sees mousedown / focus / selection like a user. */
const press = async (root: HTMLElement) => {
	await page.elementLocator(box(root)).click();
};

beforeEach(async () => {
	await page.viewport(1400, 900);
	server = new Map([['rec1', rec()]]);
	vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ success: false }), { status: 404 })));
	getReview.mockImplementation(async () => review());
	postEvent.mockImplementation(async (_r: string, id: string, command: string, textHash: string, detail: Record<string, unknown>) => {
		const cur = server.get(id)!;
		const next = {
			...cur,
			status: STATUS[command] ?? cur.status,
			history: [...cur.history, { event: command, actor: 'user', text_hash: textHash, detail: detail ?? {} }]
		};
		server.set(id, next);
		await pause(20);
		return structuredClone(next);
	});
});

afterEach(() => {
	vi.unstubAllGlobals();
	getReview.mockReset();
	postEvent.mockReset();
});

describe('recommendation checkbox in the viewer', () => {
	it('untick removes, re-tick restores, over and over (with saves in between)', async () => {
		const save = vi.fn();
		const { container, rerender } = render(ReportResponseViewer, {
			props: { visible: true, response: REPORT, reportId: 'rep1' },
			events: { save }
		} as MountOpts);
		await pause(400);
		const view = viewOf(container);
		for (let cycle = 0; cycle < 4; cycle++) {
			expect(box(container).checked, `cycle ${cycle}`).toBe(true);
			await press(container);
			await pause(150);
			expect(view.state.doc.toString(), `cycle ${cycle}: removed`).not.toContain(REC);
			expect(box(container).checked, `cycle ${cycle}: unticked`).toBe(false);
			if (cycle % 2) {
				// a save: the parent takes the text as the new response
				await rerender({ response: view.state.doc.toString() });
				await pause(200);
			}
			await press(container);
			await pause(150);
			expect(view.state.doc.toString(), `cycle ${cycle}: restored`).toContain(REC);
			expect(box(container).checked, `cycle ${cycle}: ticked`).toBe(true);
			if (cycle % 2) {
				await rerender({ response: view.state.doc.toString() });
				await pause(200);
			}
		}
		const cmds = postEvent.mock.calls.map((c) => c[2]);
		expect(cmds).toEqual(Array(4).fill(['edit', 'undo']).flat());
	});

	it('Discard after unticking puts the recommendation back (the reload does not throw) and the box keeps working', async () => {
		const { container } = render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await pause(400);
		const view = viewOf(container);
		const errors: unknown[] = [];
		const onErr = (e: ErrorEvent) => errors.push(e.error);
		window.addEventListener('error', onErr);
		await press(container);
		await pause(150);
		expect(view.state.doc.toString()).not.toContain(REC);
		await page.getByRole('button', { name: 'Discard', exact: true }).click();
		await pause(300);
		window.removeEventListener('error', onErr);
		expect(errors).toEqual([]);
		expect(view.state.doc.toString()).toBe(REPORT);
		expect(container.querySelector('[data-testid="unsaved-status"]')).toBeNull();
		expect(box(container).checked).toBe(true);
		await press(container);
		await pause(150);
		expect(view.state.doc.toString()).not.toContain(REC);
	});
});
