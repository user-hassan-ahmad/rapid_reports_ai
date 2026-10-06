// /dev/review-rail (Plan 3 C7). SYNTHETIC report and items only; the review API and the reports endpoints are mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { EditorView } from '@codemirror/view';
import type { ReviewItem, ReviewResponse } from '$lib/review/types';

const env = vi.hoisted(() => ({}) as Record<string, string | undefined>);
vi.mock('$env/dynamic/public', () => ({ env }));

const getReview = vi.fn();
const postEvent = vi.fn();
const rerun = vi.fn(async () => ({ success: true, status: 'running' }));
vi.mock('$lib/review/api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: (...a: unknown[]) => postEvent(...a),
	rerun: (...a: unknown[]) => rerun(...(a as [])),
	probe: vi.fn(),
	reprepare: vi.fn()
}));

const { load } = await import('./+page');
const { default: DevReviewRail } = await import('./+page.svelte');

const REPORT = `FINDINGS:
The spleen measures 9 cm. No ascites.

IMPRESSION:
Normal study.`;

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

function review(items: ReviewItem[]): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
	return {
		success: true,
		mode: 'shadow',
		rail: false,
		run: {
			id: 'run1',
			mode: 'shadow',
			engine_version: 'eng-7.3',
			pathway: 'quick',
			lanes,
			timings_ms: { accuracy: 1234 },
			cost: {},
			errors: { additions: 'synthetic timeout' },
			created_at: null
		},
		lanes,
		items
	};
}

const REPORTS = [
	{ id: 'rep1', description: 'CT abdomen (synthetic)', created_at: '2026-10-01T10:00:00', report_content: REPORT },
	{ id: 'rep2', description: 'No run (synthetic)', created_at: '2026-10-01T09:00:00', report_content: 'X' }
];

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const viewOf = (root: HTMLElement) => EditorView.findFromDOM(root.querySelector('.cm-editor') as HTMLElement)!;
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

beforeEach(async () => {
	await page.viewport(1400, 900);
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			const single = /\/api\/reports\/([^/?]+)$/.exec(url);
			if (single) {
				const report = REPORTS.find((r) => r.id === single[1]);
				return json(report ? { success: true, report } : { success: false, error: 'Report not found' });
			}
			if (/\/api\/reports(\?|$)/.test(url)) return json({ success: true, reports: REPORTS });
			return new Response(JSON.stringify({ success: false }), { status: 404 });
		})
	);
	getReview.mockImplementation(async (id: string) => {
		if (id === 'rep1') return review([action()]);
		throw new Error('no review');
	});
	postEvent.mockImplementation(async (_r: string, id: string) => ({ ...action(), id, status: 'applied' }));
});

afterEach(() => {
	vi.unstubAllGlobals();
	getReview.mockReset();
	postEvent.mockReset();
	rerun.mockClear();
	delete env.PUBLIC_ENABLE_DEV_ROUTES;
});

describe('/dev/review-rail guard', () => {
	it('404s unless PUBLIC_ENABLE_DEV_ROUTES is "true"', () => {
		expect(() => load()).toThrow(expect.objectContaining({ status: 404 }));
		env.PUBLIC_ENABLE_DEV_ROUTES = 'false';
		expect(() => load()).toThrow(expect.objectContaining({ status: 404 }));
		env.PUBLIC_ENABLE_DEV_ROUTES = 'true';
		expect(() => load()).not.toThrow();
	});
});

describe('/dev/review-rail page', () => {
	it('lists recent reports, marks the ones with a run, and renders the rail, marks and run meta', async () => {
		const { container } = render(DevReviewRail);
		await expect.element(page.getByText('CT abdomen (synthetic)')).toBeInTheDocument();
		await expect.element(page.getByTestId('run-badge-rep1')).toHaveTextContent('shadow');
		await page.getByRole('button', { name: /CT abdomen \(synthetic\)/ }).click();
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await pause(200);
		expect(container.querySelector('.rv-mark[data-rv-id="a1"]')?.textContent).toBe('9 cm');
		const meta = page.getByTestId('run-meta');
		await expect.element(meta).toHaveTextContent('eng-7.3');
		await expect.element(meta).toHaveTextContent('1234');
		await expect.element(meta).toHaveTextContent('synthetic timeout');
		await expect.element(meta).toHaveTextContent('accuracy');
	});

	it('loads a pasted id', async () => {
		const { container } = render(DevReviewRail);
		await page.getByLabelText('Report id').fill('rep1');
		await page.getByRole('button', { name: 'Load', exact: true }).click();
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await pause(200);
		expect(viewOf(container).state.doc.toString()).toBe(REPORT);
	});

	it('with post events off (the default), Apply changes the text and posts nothing', async () => {
		const { container } = render(DevReviewRail);
		await expect.element(page.getByLabelText('Post events')).not.toBeChecked();
		await page.getByLabelText('Report id').fill('rep1');
		await page.getByRole('button', { name: 'Load', exact: true }).click();
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await pause(200);
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(200);
		expect(viewOf(container).state.doc.toString()).toContain('The spleen measures 11 cm.');
		expect(postEvent).not.toHaveBeenCalled();
	});

	it('with post events on, Apply posts the event', async () => {
		const { container } = render(DevReviewRail);
		await page.getByLabelText('Post events').click();
		await page.getByLabelText('Report id').fill('rep1');
		await page.getByRole('button', { name: 'Load', exact: true }).click();
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await pause(200);
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		await pause(300);
		expect(viewOf(container).state.doc.toString()).toContain('11 cm');
		expect(postEvent.mock.calls.map((c) => c[2])).toEqual(['apply']);
	});
});
