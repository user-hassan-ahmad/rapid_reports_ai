// The review rail mounted in the report viewer (Plan 3 C5). SYNTHETIC report and items only; the review API and
// the workspace endpoints are mocked, every other fetch answers "not found".
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { get } from 'svelte/store';
import { EditorView } from '@codemirror/view';
import { undo } from '@codemirror/commands';
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
const { reviewRailActive } = await import('$lib/review/railActive');
const { stackMode } = await import('$lib/hybrid-stack/mode');

const REPORT = `FINDINGS:
The spleen measures 9 cm. No ascites.

IMPRESSION:
Normal study.`;

const OPTIONS = [{ id: 'opt0', kind: 'recommendation' as const, sentence: 'MRI is recommended.', reason: '' }];

const STATUS: Record<string, ReviewItem['status']> = {
	apply: 'applied',
	edit: 'applied',
	undo: 'open',
	dismiss: 'dismissed',
	restore: 'open'
};

function action(): ReviewItem {
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
		engine_version: 'test'
	};
}

function review(mode: 'live' | 'shadow', rail: boolean, items: ReviewItem[]): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
	return {
		success: true,
		mode,
		rail,
		run: {
			id: 'run1',
			mode,
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

// `render` supplies `target`; the typed mount options demand it anyway.
type MountOpts = Parameters<typeof render<typeof ReportResponseViewer>>[1];

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const viewOf = (root: HTMLElement) => EditorView.findFromDOM(root.querySelector('.cm-editor') as HTMLElement)!;

beforeEach(async () => {
	await page.viewport(1400, 900);
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => new Response(JSON.stringify({ success: false }), { status: 404 }))
	);
	postEvent.mockImplementation(async (_r: string, id: string, command: string) => ({
		...action(),
		id,
		status: STATUS[command] ?? 'open'
	}));
});

afterEach(() => {
	vi.unstubAllGlobals();
	getReview.mockReset();
	postEvent.mockReset();
});

describe('report viewer with the review rail off', () => {
	it('keeps today’s UI: optional additions shown, no rail, rail flag false', async () => {
		getReview.mockResolvedValue(review('shadow', false, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, options: OPTIONS, reportId: 'rep1' });
		await pause(300);
		expect(getReview).toHaveBeenCalledWith('rep1');
		await expect.element(page.getByRole('checkbox').first()).toBeInTheDocument();
		expect(document.querySelector('[data-testid="review-rail"]')).toBeNull();
		expect(get(reviewRailActive)).toBe(false);
	});

	it('copy sends the live editor document', async () => {
		getReview.mockResolvedValue(review('shadow', false, []));
		const copy = vi.fn();
		const { container } = render(ReportResponseViewer, {
			props: { visible: true, response: REPORT, reportId: 'rep1' },
			events: { copy }
		} as MountOpts);
		await pause(300);
		const view = viewOf(container);
		view.dispatch({ changes: { from: view.state.doc.length, insert: ' Edited.' } });
		await page.getByRole('button', { name: 'Copy report' }).click();
		expect(copy).toHaveBeenCalled();
		expect(copy.mock.calls[0][0].detail.content).toBe(REPORT + ' Edited.');
	});
});

describe('report viewer with the review rail on', () => {
	it('mounts the rail, hides optional additions and sets the rail flag', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		const { container, unmount } = render(ReportResponseViewer, {
			visible: true,
			response: REPORT,
			options: OPTIONS,
			reportId: 'rep1'
		});
		await pause(400);
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		expect(document.querySelectorAll('input[type="checkbox"]').length).toBe(0);
		expect(get(reviewRailActive)).toBe(true);
		const mark = container.querySelector('.rv-mark[data-rv-id="a1"]');
		expect(mark?.textContent).toBe('9 cm');
		unmount();
		expect(get(reviewRailActive)).toBe(false);
	});

	it('Apply changes the editor text, marks unsaved, posts apply; Cmd-Z posts undo', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		const { container } = render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await pause(400);
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(200);
		const view = viewOf(container);
		expect(view.state.doc.toString()).toContain('The spleen measures 11 cm.');
		await expect.element(page.getByTestId('unsaved-status')).toBeInTheDocument();
		expect(postEvent.mock.calls.map((c) => c[2])).toEqual(['apply']);
		expect(postEvent.mock.calls[0][3]).toMatch(/^[0-9a-f]{16}$/);

		undo(view);
		await pause(200);
		expect(view.state.doc.toString()).toBe(REPORT);
		expect(postEvent.mock.calls.map((c) => c[2])).toEqual(['apply', 'undo']);
	});

	it('copy sends the live editor document', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		const copy = vi.fn();
		render(ReportResponseViewer, { props: { visible: true, response: REPORT, reportId: 'rep1' }, events: { copy } } as MountOpts);
		await pause(400);
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(100);
		await page.getByRole('button', { name: 'Copy report' }).click();
		expect(copy.mock.calls[0][0].detail.content).toContain('11 cm');
	});

	it('save sends the kept review item ids', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		const save = vi.fn();
		render(ReportResponseViewer, { props: { visible: true, response: REPORT, reportId: 'rep1' }, events: { save } } as MountOpts);
		await pause(400);
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(100);
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		expect(save.mock.calls[0][0].detail.reviewAppliedItemIds).toEqual(['a1']);
	});

	it('a regenerated report keeps the marks it can place and reloads the store', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		const { container, rerender } = render(ReportResponseViewer, {
			visible: true,
			response: REPORT,
			reportId: 'rep1'
		});
		await pause(400);
		const calls = getReview.mock.calls.length;
		const next = REPORT.replace('Normal study.', 'Splenic size within limits.');
		await rerender({ response: next });
		await pause(300);
		expect(viewOf(container).state.doc.toString()).toBe(next);
		expect(container.querySelector('.rv-mark[data-rv-id="a1"]')?.textContent).toBe('9 cm');
		expect(getReview.mock.calls.length).toBeGreaterThan(calls);
	});
});

describe('after generation in stack mode (P2c, D4/D13): no /enhance, no /api/audit, no guideline pane', () => {
	const urls = () => (vi.mocked(fetch).mock.calls as unknown as [RequestInfo | URL][]).map(([u]) => String(u));
	afterEach(() => stackMode.set(false));

	it('stack off: the rail loads /enhance for its Guidelines tab (today)', async () => {
		stackMode.set(false);
		getReview.mockResolvedValue(review('live', true, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep-off-1' });
		await pause(400);
		expect(urls().some((u) => u.includes('/api/reports/rep-off-1/enhance'))).toBe(true);
		await expect.element(page.getByRole('tab', { name: 'Guidelines' })).toBeInTheDocument();
	});

	it('stack on: the rail never calls /enhance and shows no Guidelines tab', async () => {
		stackMode.set(true);
		getReview.mockResolvedValue(review('live', true, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep-on-1' });
		await pause(400);
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		expect(urls().filter((u) => u.includes('/enhance'))).toEqual([]);
		expect(page.getByRole('tab', { name: 'Guidelines' }).elements()).toHaveLength(0);
	});

	it('stack off without a rail: /api/audit auto-fires (today); stack on: never', async () => {
		stackMode.set(false);
		getReview.mockResolvedValue(review('shadow', false, []));
		const a = render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep-off-2' });
		await pause(400);
		expect(urls().some((u) => u.endsWith('/api/audit'))).toBe(true);
		a.unmount();
		vi.mocked(fetch).mockClear();
		stackMode.set(true);
		render(ReportResponseViewer, { visible: true, response: REPORT + ' ', reportId: 'rep-on-2' });
		await pause(400);
		expect(urls().filter((u) => u.includes('/api/audit') || u.includes('/validation-status'))).toEqual([]);
	});
});

describe('stack check flags reach the rail as open items (P2a → P2c)', () => {
	it.each(['removed_asserted', 'removed_unverified', 'undictated_number', 'value_missing'])('%s renders with its label', async (kind) => {
		stackMode.set(true);
		const flag: ReviewItem = { ...action(), id: `f-${kind}`, key: `f-${kind}`, kind, cls: 'action', edit: null,
			label: `Check flag ${kind}`, reason: `Check flag ${kind}` } as unknown as ReviewItem;
		getReview.mockResolvedValue(review('live', true, [flag]));
		const r = render(ReportResponseViewer, { visible: true, response: REPORT, reportId: `rep-flag-${kind}` });
		await pause(400);
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await expect.element(page.getByTestId('review-rail').getByText(`Check flag ${kind}`).first()).toBeInTheDocument();
		r.unmount();
		stackMode.set(false);
	});
});
