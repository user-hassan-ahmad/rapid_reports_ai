// Rail polish in the report viewer: rail placement before the review loads (no Copilot flash), the legend under the
// "Report Editor" title, and the Guidelines tab fed by /enhance with "Ask" routed through the rail's command path.
// SYNTHETIC report and items only; the review, chat and workspace calls are mocked; fetch answers /enhance.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { get } from 'svelte/store';
import type { ReviewItem, ReviewResponse } from '$lib/review/types';

const getReview = vi.fn();
vi.mock('$lib/review/api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: vi.fn(async () => ({})),
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
vi.mock('$lib/review/chat', async (orig) => ({
	...(await orig<typeof import('$lib/review/chat')>()),
	loadThread: vi.fn(async () => [])
}));

const { default: ReportResponseViewer } = await import('./ReportResponseViewer.svelte');
const rail = await import('$lib/review/railActive');
const { forgetEnhancement } = await import('$lib/guidelines/enhance');

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

function review(mode: 'live' | 'shadow', on: boolean, items: ReviewItem[]): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
	return {
		success: true,
		mode,
		rail: on,
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

const GUIDELINES = [
	{
		finding: 'Synthetic splenic finding',
		finding_short_label: 'Synthetic splenic finding',
		urgency_tier: 'routine',
		follow_up_actions: [
			{ modality: 'US', timing: '6 months', indication: 'synthetic', urgency: 'routine', guideline_source: 'X' }
		]
	}
];

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const enhanceCalls = () =>
	(fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter((c) => String(c[0]).endsWith('/enhance'));

beforeEach(async () => {
	await page.viewport(1400, 900);
	rail.resetRailMemory();
	forgetEnhancement('rep1');
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) =>
			String(url).endsWith('/enhance')
				? new Response(
						JSON.stringify({
							success: true,
							findings: [],
							guidelines: GUIDELINES,
							urgency_signals: [],
							applicable_guidelines: []
						}),
						{ status: 200 }
					)
				: new Response(JSON.stringify({ success: false }), { status: 404 })
		)
	);
});

afterEach(() => {
	vi.unstubAllGlobals();
	getReview.mockReset();
});

function deferred() {
	let resolve!: (r: ReviewResponse) => void;
	const promise = new Promise<ReviewResponse>((r) => (resolve = r));
	return { promise, resolve };
}

describe('rail placement before the review loads (no Copilot flash)', () => {
	it('first-ever load: the skeleton shows at once while the GET is out (aside held), and goes when there is no rail', async () => {
		const d = deferred();
		getReview.mockReturnValueOnce(d.promise);
		const holds = rail.reviewRailHoldsAside('rep1');
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument(); // before any /review response
		expect(document.querySelector<HTMLElement>('[data-testid="review-rail"]')!.getBoundingClientRect().width).toBe(340);
		expect(get(holds)).toBe(true); // pending, mode unknown: no aside
		d.resolve(review('shadow', false, []));
		await pause(200);
		expect(document.querySelector('[data-testid="review-rail"]')).toBeNull();
		expect(get(holds)).toBe(false);
		expect(get(rail.reviewRailExpected)).toBe(false);
	});

	it('first-ever load with a rail: skeleton first, then the items fade in at the same width (no empty → populated jump)', async () => {
		const d = deferred();
		getReview.mockReturnValueOnce(d.promise);
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		expect(document.body.textContent).not.toContain('Nothing to review');
		d.resolve(review('live', true, [action()]));
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		const slot = document.querySelector<HTMLElement>('[data-testid="review-rail"]')!;
		expect(slot.getBoundingClientRect().width).toBe(340);
		expect(getComputedStyle(slot.querySelector('.rv-items')!).animationName).toContain('rv-fade-in');
	});

	it('the mode is remembered across tabs (localStorage): a new tab shows no skeleton when the last answer was "no rail"', async () => {
		rail.rememberRailMode(false);
		expect(localStorage.getItem('rr_review_rail')).toBe('0');
		sessionStorage.removeItem('rr_review_rail');
		const d = deferred();
		getReview.mockReturnValueOnce(d.promise);
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await pause(150);
		expect(document.querySelector('[data-testid="rv-skeleton"]')).toBeNull();
		d.resolve(review('shadow', false, []));
	});

	it('first-ever load with a rail: held throughout, and the session remembers the mode', async () => {
		const d = deferred();
		getReview.mockReturnValueOnce(d.promise);
		const holds = rail.reviewRailHoldsAside('rep1');
		const seen: boolean[] = [];
		const stop = holds.subscribe((v) => seen.push(v));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await pause(100);
		d.resolve(review('live', true, [action()]));
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await pause(100);
		stop();
		expect(seen.every(Boolean)).toBe(true); // never released in between
		expect(sessionStorage.getItem('rr_review_rail')).toBe('1');
	});

	it('rail expected (session cache): the rail slot renders its skeleton at once, at the final width', async () => {
		rail.rememberRailMode(true);
		const d = deferred();
		getReview.mockReturnValueOnce(d.promise);
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		const slot = document.querySelector<HTMLElement>('[data-testid="review-rail"]')!;
		const width = slot.getBoundingClientRect().width;
		expect(width).toBe(340);
		expect(get(rail.reviewRailHoldsAside('rep1'))).toBe(true);
		d.resolve(review('live', true, [action()]));
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(document.querySelector<HTMLElement>('[data-testid="review-rail"]')!.getBoundingClientRect().width).toBe(
			width
		);
	});

	it('switching between two rail reports never releases the aside (old id or new)', async () => {
		getReview.mockResolvedValueOnce(review('live', true, [action()]));
		const { rerender } = render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		const seen: boolean[] = [];
		const stops = [
			rail.reviewRailHoldsAside('rep1').subscribe((v) => seen.push(v)),
			rail.reviewRailHoldsAside('rep2').subscribe((v) => seen.push(v))
		];
		const d = deferred();
		getReview.mockReturnValueOnce(d.promise);
		await rerender({ visible: true, response: REPORT, reportId: 'rep2' });
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		d.resolve(review('live', true, [{ ...action(), report_id: 'rep2' }]));
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		stops.forEach((f) => f());
		expect(seen.every(Boolean)).toBe(true);
	});

	it('rail expected but this report has none: the skeleton goes and the aside is released', async () => {
		rail.rememberRailMode(true);
		getReview.mockResolvedValueOnce(review('shadow', false, []));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await pause(300);
		expect(document.querySelector('[data-testid="review-rail"]')).toBeNull();
		expect(get(rail.reviewRailHoldsAside('rep1'))).toBe(false);
	});
});

describe('legend', () => {
	it('sits directly under the Report Editor title, not in the rail', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		const legend = document.querySelector<HTMLElement>('[data-testid="review-legend"]')!;
		expect(legend).not.toBeNull();
		expect(legend.closest('[data-testid="review-rail"]')).toBeNull();
		const title = page.getByRole('heading', { name: 'Report Editor' }).element();
		expect(title.nextElementSibling).toBe(legend);
		expect(legend.textContent).toContain('AI-generated');
		expect(document.querySelector('[aria-label="Density"]')).toBeNull();
	});

	it('compact labels (full meaning on hover), wrapping instead of scrolling; the copy button stays on the controls line', async () => {
		await page.viewport(1280, 800);
		getReview.mockResolvedValue(review('live', true, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		const legend = document.querySelector<HTMLElement>('[data-testid="review-legend"]')!;
		const items = [...legend.querySelectorAll<HTMLElement>('[data-rv-label], button[data-rv-filter]')];
		expect(items.map((b) => b.querySelector('.rv-legend-label')?.textContent)).toEqual([
			'Dictated',
			'Removed by you',
			'AI-generated',
			'Removed (contradicts dictation)'
		]);
		expect(legend.textContent).not.toContain('(AI)');
		expect(items[2].title).toMatch(/normals.*pertinent negatives.*synthesis/i);
		expect(items[3].title).toContain('contradicts your dictation');
		expect(legend.scrollWidth).toBeLessThanOrEqual(legend.clientWidth + 1);
		const controls = document.querySelector<HTMLElement>('[data-testid="editor-controls"]')!;
		const copy = controls.querySelector<HTMLElement>('[aria-label="Copy report"]')!;
		await page.viewport(700, 800);
		await pause(50);
		// one line: every control (the copy button included) shares the row's vertical band
		const mid = (e: Element) => {
			const r = e.getBoundingClientRect();
			return (r.top + r.bottom) / 2;
		};
		const kids = [...controls.children].filter((c) => (c as HTMLElement).offsetWidth > 0);
		expect(kids.length).toBeGreaterThan(1);
		for (const k of kids) expect(Math.abs(mid(k) - mid(copy))).toBeLessThan(8);
		await page.viewport(414, 896);
	});

	it('AI-generated is on by default; pressing it turns the layer off in the editor (plain text) and on again', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		const editor = () => document.querySelector<HTMLElement>('.cm-editor')!;
		expect(editor().getAttribute('data-rv-emph')).toBe('ai');
		const ai = page.getByRole('button', { name: /^AI-generated$/ });
		await expect.element(ai).toHaveAttribute('aria-pressed', 'true');
		await ai.click();
		await expect.element(ai).toHaveAttribute('aria-pressed', 'false');
		expect(editor().hasAttribute('data-rv-emph')).toBe(false);
		await ai.click();
		expect(editor().getAttribute('data-rv-emph')).toBe('ai');
		expect(document.querySelector('[data-testid="review-legend"]')!.textContent).not.toContain('Recommendations');
	});

	it('is absent with the rail off', async () => {
		getReview.mockResolvedValue(review('shadow', false, []));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await pause(300);
		expect(document.querySelector('[data-testid="review-legend"]')).toBeNull();
	});
});

describe('Guidelines tab', () => {
	it('renders the /enhance guidelines in the rail; Ask fills the rail chat composer (command path)', async () => {
		getReview.mockResolvedValue(review('live', true, [action()]));
		render(ReportResponseViewer, { visible: true, response: REPORT, reportId: 'rep1' });
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await page.getByRole('tab', { name: 'Guidelines' }).click();
		await expect.element(page.getByText('Synthetic splenic finding')).toBeInTheDocument();
		const panel = document.querySelector('[data-testid="guidelines-panel"]')!;
		expect(panel.closest('[data-testid="review-rail"]')).not.toBeNull();
		expect(enhanceCalls().length).toBe(1); // the prefetch and the tab share one request
		expect(document.body.textContent).not.toContain('Open guidelines'); // no link-out to the Copilot
		await page.getByRole('button', { name: 'Ask →', exact: true }).click();
		await expect
			.element(page.getByRole('textbox', { name: 'Chat message' }))
			.toHaveValue('Re: Synthetic splenic finding — ');
	});
});
