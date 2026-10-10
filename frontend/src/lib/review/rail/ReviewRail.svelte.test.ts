import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { createRawSnippet } from 'svelte';
import type { ReviewItem, ReviewResponse } from '../types';

const getReview = vi.fn();
vi.mock('../api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: vi.fn(),
	rerun: vi.fn()
}));

const { createReviewStore } = await import('../store');
const { default: ReviewRail } = await import('./ReviewRail.svelte');

// SYNTHETIC items only.
function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id' | 'kind' | 'cls'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		label: over.id,
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}
const at = (start: number, text = 'x') => ({ start, end: start + text.length, text });

const ITEMS: ReviewItem[] = [
	item({
		id: 'n1',
		kind: 'assumed_normal',
		cls: 'info',
		section: 'Liver',
		label: 'Liver normal',
		anchor: at(5)
	}),
	item({
		id: 'a1',
		kind: 'measurement',
		cls: 'action',
		lane: 'accuracy',
		section: 'Spleen',
		label: 'Measurement differs',
		reason: 'The dictation gives 11 cm.',
		anchor: at(40, '9 cm'),
		edit: { mode: 'replace', find: '9 cm', replace: '11 cm' }
	}),
	item({
		id: 'm1',
		kind: 'wording',
		cls: 'minor',
		section: 'Liver',
		label: 'Tidy wording',
		anchor: at(20),
		edit: { mode: 'replace', find: 'x', replace: 'y' }
	}),
	item({
		id: 'i1',
		kind: 'note',
		cls: 'info',
		section: 'Liver',
		label: 'Prior study mentioned',
		anchor: at(10)
	}),
	item({
		id: 'u1',
		kind: 'omission',
		cls: 'action',
		section: null,
		label: 'Unplaced finding',
		anchor: null
	}),
	item({
		id: 'p1',
		kind: 'omission',
		cls: 'action',
		status: 'pre_applied',
		section: 'Kidneys',
		label: 'Renal calculi',
		anchor: at(60),
		edit: { mode: 'insert', after: 'x', replace: 'No renal calculi.' }
	}),
	item({
		id: 'r1',
		kind: 'removed',
		cls: 'action',
		status: 'pre_applied',
		section: 'Kidneys',
		label: 'Kidneys normal',
		anchor: at(70, ''),
		evidence: { removed_text: 'The kidneys are normal.' }
	}),
	item({
		id: 'c1',
		kind: 'check',
		cls: 'minor',
		section: 'Liver',
		label: 'No hydronephrosis',
		anchor: at(30),
		evidence: { check_reason: 'uncertain' }
	}),
	item({
		id: 'c2',
		kind: 'check',
		cls: 'minor',
		section: 'Spleen',
		label: 'Spleen 12 cm',
		anchor: at(45),
		evidence: { check_reason: 'number' }
	}),
	item({
		id: 'o1',
		kind: 'option',
		cls: 'minor',
		lane: 'additions',
		label: 'No free fluid',
		reason: 'often reported',
		edit: { mode: 'insert', after: 'x', replace: 'No free fluid.' }
	}),
	item({ id: 'f1', kind: 'note', cls: 'suppress', section: 'Liver', label: 'suppressed' }),
	item({
		id: 'f2',
		kind: 'wording',
		cls: 'minor',
		status: 'dismissed',
		section: 'Liver',
		label: 'dismissed one'
	})
];

function response(over: Partial<ReviewResponse> = {}): ReviewResponse {
	return {
		success: true,
		mode: 'live',
		rail: true,
		run: {
			id: 'run1',
			mode: 'live',
			engine_version: 'test',
			pathway: 'quick',
			lanes: { coverage: 'done', accuracy: 'done', additions: 'done' },
			timings_ms: {},
			cost: {},
			errors: {},
			created_at: null
		},
		lanes: { coverage: 'done', accuracy: 'done', additions: 'done' },
		items: ITEMS,
		...over
	};
}

async function mount(
	resp: ReviewResponse | null = response(),
	props: Record<string, unknown> = {}
) {
	const store = createReviewStore('rep1');
	if (resp) {
		getReview.mockResolvedValueOnce(resp);
		await store.load();
	}
	store.setSectionOrder(['Liver', 'Spleen', 'Kidneys']);
	const onCommand = vi.fn();
	const onDensity = vi.fn();
	const screen = render(ReviewRail, { store, onCommand, onDensity, layout: 'wide', ...props });
	return { store, onCommand, onDensity, screen };
}

const rail = () => document.querySelector<HTMLElement>('[data-testid="review-rail"]');

afterEach(() => {
	getReview.mockReset();
});

describe('ReviewRail', () => {
	it('groups the flagged issues by section in report order, Unanchored last; no checks, suggestions, minor rows, normals or info', async () => {
		await mount();
		await expect.element(page.getByRole('heading', { name: 'Spleen' })).toBeInTheDocument();
		const headings = [...rail()!.querySelectorAll('[data-rv-section]')].map((h) =>
			h.getAttribute('data-rv-section')
		);
		expect(headings).toEqual(['Spleen', 'Kidneys', 'Unanchored']);
		const sectioned = [...rail()!.querySelectorAll('[data-rv-section]')].flatMap((h) =>
			[...h.closest('section')!.querySelectorAll('[data-rv-item]')].map((e) => e.getAttribute('data-rv-item'))
		);
		expect(sectioned).toEqual(['a1', 'p1', 'r1', 'u1']);
		for (const id of ['n1', 'i1', 'c1', 'c2', 'm1', 'o1']) expect(rail()!.querySelector(`[data-rv-item="${id}"]`)).toBeNull();
		expect(rail()!.textContent).not.toContain('Liver normal');
	});

	it('renders the action card and the pre-applied variants', async () => {
		await mount();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-item="a1"]')!.getAttribute('data-rv-variant')).toBe(
			'card'
		);
		const p1 = rail()!.querySelector<HTMLElement>('[data-rv-item="p1"]')!;
		expect(p1.textContent).toContain('added from your dictation');
		const r1 = rail()!.querySelector<HTMLElement>('[data-rv-item="r1"]')!;
		expect(r1.textContent).toContain('removed · contradicts your dictation');
		expect(r1.textContent).toContain('The kidneys are normal.');
	});

	it('a removed row in a narrow rail keeps a readable label column; its actions wrap instead (Gate G)', async () => {
		await mount();
		await expect.element(page.getByText('Kidneys normal')).toBeInTheDocument();
		rail()!.style.width = '330px';
		const r1 = rail()!.querySelector<HTMLElement>('[data-rv-item="r1"]')!;
		const main = r1.querySelector<HTMLElement>('.rv-row-main')!;
		const actions = r1.querySelector<HTMLElement>('.rv-row-actions')!;
		await new Promise((r) => requestAnimationFrame(() => r(null)));
		const row = r1.getBoundingClientRect().width;
		expect(main.getBoundingClientRect().width).toBeGreaterThanOrEqual(row * 0.4);
		expect(actions.getBoundingClientRect().width).toBeLessThanOrEqual(row * 0.6);
		expect(r1.scrollWidth).toBeLessThanOrEqual(r1.clientWidth + 1);
	});

	it('pre-applied undo and restore call the commands', async () => {
		const { onCommand } = await mount();
		await page.getByRole('button', { name: /undo/i }).first().click();
		expect(onCommand).toHaveBeenCalledWith('undo', 'p1');
		await page
			.getByRole('button', { name: /restore/i })
			.first()
			.click();
		expect(onCommand).toHaveBeenCalledWith('restore', 'r1');
	});

	it('no checks in the rail: no "to check" group, no check rows (checks live only in the editor)', async () => {
		await mount();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-group="checks"]')).toBeNull();
		expect(rail()!.textContent).not.toMatch(/to check/);
		expect(rail()!.querySelector('[data-rv-variant="check"]')).toBeNull();
		expect(rail()!.textContent).not.toContain('No hydronephrosis');
		expect(rail()!.textContent).not.toContain('Spleen 12 cm');
	});

	it('a conflict check (cls action) is a rail card with Remove (its apply command) and Dismiss; minor checks are not', async () => {
		const conflict = item({
			id: 'k1',
			kind: 'check',
			cls: 'action',
			lane: 'accuracy',
			section: 'Liver',
			label: 'Conflicts with your dictation',
			anchor: at(80, 'No focal lesion.'),
			evidence: { check_reason: 'conflict', source: 'brief', brief_reason: 'brief_kept' },
			edit: { mode: 'remove', find: 'No focal lesion.' }
		});
		const { onCommand } = await mount(response({ items: [...ITEMS, conflict] }));
		await expect.element(page.getByText('Conflicts with your dictation')).toBeInTheDocument();
		const k1 = rail()!.querySelector<HTMLElement>('[data-rv-item="k1"]')!;
		expect(k1.getAttribute('data-rv-variant')).toBe('card');
		for (const id of ['c1', 'c2']) expect(rail()!.querySelector(`[data-rv-item="${id}"]`), id).toBeNull();
		await page.getByRole('button', { name: 'Remove: Conflicts with your dictation' }).click();
		expect(onCommand).toHaveBeenCalledWith('apply', 'k1');
		expect(k1.querySelector('[aria-label="Apply: Conflicts with your dictation"]')).toBeNull();
		expect(k1.textContent).toContain('Remove');
		await page.getByRole('button', { name: 'Dismiss: Conflicts with your dictation' }).click();
		expect(onCommand).toHaveBeenCalledWith('dismiss', 'k1');
	});

	it('a conflict card with no edit offers Ask in chat and Dismiss, no Apply', async () => {
		const conflict = item({
			id: 'k2',
			kind: 'check',
			cls: 'action',
			lane: 'accuracy',
			section: 'Liver',
			label: 'Conflict without a fix',
			anchor: at(80, 'No focal lesion.'),
			evidence: { check_reason: 'conflict', source: 'brief', brief_reason: 'removal_blocked' }
		});
		await mount(response({ items: [...ITEMS, conflict] }));
		await expect.element(page.getByText('Conflict without a fix')).toBeInTheDocument();
		const k2 = rail()!.querySelector<HTMLElement>('[data-rv-item="k2"]')!;
		expect(k2.getAttribute('data-rv-variant')).toBe('card');
		expect(k2.querySelector('[aria-label="Apply: Conflict without a fix"]')).toBeNull();
		expect(k2.querySelector('[aria-label="Ask in chat: Conflict without a fix"]')).not.toBeNull();
		expect(k2.querySelector('[aria-label="Dismiss: Conflict without a fix"]')).not.toBeNull();
	});

	it('no suggestions, recommendations or AI synthesis in the rail (they live in the editor)', async () => {
		const extra = [
			item({ id: 'rec1', kind: 'recommendation', cls: 'minor', section: 'Spleen', label: 'Follow-up advised', anchor: at(50), edit: { mode: 'remove', find: 'x' } }),
			item({ id: 's1', kind: 'ai_generated', cls: 'info', lane: 'accuracy', section: 'Spleen', label: 'Synthesis clause', anchor: at(55) }),
			item({ id: 'g1', kind: 'classification', cls: 'minor', lane: 'additions', label: 'Borderline resectable', edit: { mode: 'insert', after: 'x', replace: 'Borderline resectable.' } })
		];
		await mount(response({ items: [...ITEMS, ...extra] }));
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		for (const id of ['o1', 'm1', 'rec1', 's1', 'g1']) expect(rail()!.querySelector(`[data-rv-item="${id}"]`), id).toBeNull();
		expect(rail()!.querySelector('[data-rv-group="suggestions"]')).toBeNull();
		expect(rail()!.textContent).not.toMatch(/Suggestions|Options/);
	});

	it('no "other checks passed" fold: answered and suppressed items are not in the rail', async () => {
		await mount();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-group="folded"]')).toBeNull();
		expect(rail()!.textContent).not.toMatch(/checks passed/);
		expect(rail()!.textContent).not.toContain('dismissed one');
	});

	it('the status line counts only what the rail shows', async () => {
		await mount();
		// open: a1, u1 (flagged issues); checks, minor rows and options are not counted
		await expect.element(page.getByRole('status')).toHaveTextContent('2 to review');
	});

	it('Apply on a card calls the command callback; clicking a row opens the item', async () => {
		const { onCommand } = await mount();
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		expect(onCommand).toHaveBeenCalledWith('apply', 'a1');
		await page.getByRole('button', { name: 'Open: Renal calculi' }).click();
		expect(onCommand).toHaveBeenCalledWith('open_item', 'p1');
		await page.getByRole('button', { name: 'Dismiss: Measurement differs' }).click();
		expect(onCommand).toHaveBeenCalledWith('dismiss', 'a1');
	});

	it('header: Re-review; no legend and no density toggle in the rail', async () => {
		const { onCommand } = await mount();
		await page.getByRole('button', { name: 'Re-review' }).click();
		expect(onCommand).toHaveBeenCalledWith('rerun');
		expect(rail()!.querySelector('[data-rv-legend]')).toBeNull();
		expect(rail()!.querySelector('[aria-label="Density"]')).toBeNull();
		expect(rail()!.textContent).not.toMatch(/Quiet|Hidden/);
	});

	it('open action cards lead their section, the rest keep report order', async () => {
		const extra = [
			item({ id: 'a0', kind: 'measurement', cls: 'action', status: 'applied', section: 'Spleen', label: 'Early applied', anchor: at(5), edit: { mode: 'replace', find: 'x', replace: 'z' } }),
			item({ id: 'a2', kind: 'measurement', cls: 'action', section: 'Spleen', label: 'Late action', anchor: at(90), edit: { mode: 'replace', find: 'x', replace: 'z' } })
		];
		await mount(response({ items: [...ITEMS, ...extra] }));
		await expect.element(page.getByText('Late action')).toBeInTheDocument();
		const spleen = rail()!.querySelector('[data-rv-section="Spleen"]')!.closest('section')!;
		const ids = [...spleen.querySelectorAll('[data-rv-item]')].map((e) => e.getAttribute('data-rv-item'));
		expect(ids).toEqual(['a1', 'a2', 'a0']);
	});

	it('dev controls: the legend and density toggle (Quiet default)', async () => {
		const { onDensity } = await mount(response(), { devControls: true });
		await expect
			.element(page.getByRole('button', { name: 'Quiet' }))
			.toHaveAttribute('aria-pressed', 'true');
		await page.getByRole('button', { name: 'Full' }).click();
		expect(onDensity).toHaveBeenCalledWith('full');
		await expect
			.element(page.getByRole('button', { name: 'Full' }))
			.toHaveAttribute('aria-pressed', 'true');
		expect(rail()!.querySelector('[data-rv-legend]')!.textContent).toContain('AI highlights');
	});

	it('pending: a fixed-width skeleton before the store answers, the same width once items arrive (no shift)', async () => {
		const store = createReviewStore('rep1');
		let resolve!: (r: ReviewResponse) => void;
		getReview.mockReturnValueOnce(new Promise<ReviewResponse>((r) => (resolve = r)));
		const loading = store.load();
		const screen = render(ReviewRail, { store, onCommand: vi.fn(), pending: true, layout: 'wide' });
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		await expect.element(page.getByText('Reviewing…')).toBeInTheDocument();
		const before = rail()!.getBoundingClientRect().width;
		expect(before).toBe(340);
		resolve(response());
		await loading;
		await screen.rerender({ store, onCommand: vi.fn(), pending: false, layout: 'wide' });
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.getBoundingClientRect().width).toBe(before);
		// the items fade in, never pop
		expect(getComputedStyle(rail()!.querySelector('.rv-items')!).animationName).toContain('rv-fade-in');
	});

	it('a queued run with no lanes yet keeps the skeleton (no "Nothing to review" flash before the items)', async () => {
		const { store } = await mount(response({ items: [], lanes: {}, run: null, running: true } as Partial<ReviewResponse>));
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		expect(rail()!.textContent).not.toContain('Nothing to review');
		getReview.mockResolvedValueOnce(response());
		await store.load();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-testid="rv-skeleton"]')).toBeNull();
	});

	it('polls keep a steady body: the skeleton stays while lanes run with nothing yet; unchanged rows keep their DOM', async () => {
		const running = { coverage: 'running', accuracy: '', additions: '' };
		const { store } = await mount(response({ items: [], lanes: running }));
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		getReview.mockResolvedValueOnce(response({ items: [], lanes: running }));
		const p = store.load(); // a poll: loading flips, the skeleton must not
		expect(rail()!.querySelector('[data-testid="rv-skeleton"]')).not.toBeNull();
		await p;
		expect(rail()!.querySelector('[data-testid="rv-skeleton"]')).not.toBeNull();
		getReview.mockResolvedValueOnce(response({ items: ITEMS.map((i) => structuredClone(i)), lanes: running }));
		await store.load();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		const card = rail()!.querySelector('[data-rv-item="a1"]');
		getReview.mockResolvedValueOnce(response({ items: ITEMS.map((i) => structuredClone(i)) }));
		await store.load();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-item="a1"]')).toBe(card);
	});

	it('renders nothing in shadow or off mode unless forced', async () => {
		const a = await mount(response({ mode: 'shadow' }));
		expect(rail()).toBeNull();
		a.screen.unmount();
		const b = await mount(response({ mode: 'off', items: [] }));
		expect(rail()).toBeNull();
		b.screen.unmount();
		await mount(response({ mode: 'shadow' }), { force: true });
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
	});

	it('states: skeleton while loading, Reviewing… while lanes run, Review incomplete on a failed lane', async () => {
		const store = createReviewStore('rep1');
		let resolve!: (r: ReviewResponse) => void;
		getReview.mockReturnValueOnce(new Promise<ReviewResponse>((r) => (resolve = r)));
		const loading = store.load();
		const first = render(ReviewRail, { store, onCommand: vi.fn(), force: true, layout: 'wide' });
		await expect.element(page.getByTestId('rv-skeleton')).toBeInTheDocument();
		resolve(response({ lanes: { coverage: 'done', accuracy: '', additions: '' } }));
		await loading;
		await expect.element(page.getByText('Reviewing…')).toBeInTheDocument();
		first.unmount();
		await mount(response({ lanes: { coverage: 'done', accuracy: 'failed', additions: 'done' } }));
		await expect.element(page.getByText('Review incomplete')).toBeInTheDocument();
	});

	it('shows "updating…" on items being re-prepared', async () => {
		await mount(response(), { updating: new Set(['p1']) });
		await expect.poll(() => rail()?.querySelector('[data-rv-item="p1"]')).toBeTruthy();
		const p1 = rail()!.querySelector<HTMLElement>('[data-rv-item="p1"]')!;
		expect(p1.textContent).toContain('updating…');
	});

	it('collapses to a strip with the open count when narrow, opening as an overlay', async () => {
		await mount(response(), { layout: 'narrow' });
		// open = what the rail shows: a1, u1
		const strip = page.getByRole('button', { name: /2 open/ });
		await expect.element(strip).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-item="a1"]')).toBeNull();
		await strip.click();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
	});

	it('Guidelines tab shows the guidelines snippet', async () => {
		const guidelines = createRawSnippet(() => ({ render: () => '<p>Guideline body</p>' }));
		await mount(response(), { guidelines });
		await page.getByRole('tab', { name: 'Guidelines' }).click();
		await expect.element(page.getByText('Guideline body')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-item="a1"]')).toBeNull();
	});

	it('Edit on an action card (moved from the old popover) sends edit with the replacement', async () => {
		const { onCommand } = await mount();
		await page.getByRole('button', { name: 'Edit: Measurement differs' }).click();
		const input = page.getByRole('textbox', { name: 'Replacement for: Measurement differs' });
		await expect.element(input).toHaveValue('11 cm');
		await input.fill('12 cm');
		await page.getByRole('button', { name: 'Save' }).click();
		expect(onCommand).toHaveBeenCalledWith('edit', 'a1', { replacement: '12 cm' });
	});

	it('reveal (the inline control’s › on a flagged issue) scrolls to the card, highlights and focuses it', async () => {
		const { screen, store, onCommand } = await mount();
		await expect.element(page.getByText('Unplaced finding')).toBeInTheDocument();
		await screen.rerender({ store, onCommand, layout: 'wide', reveal: { id: 'u1', seq: 1 } });
		const card = rail()!.querySelector<HTMLElement>('[data-rv-item="u1"]')!;
		await expect.poll(() => card.classList.contains('rv-revealed')).toBe(true);
		expect(card.contains(document.activeElement)).toBe(true);
	});

	it('shows an urgency banner at the top', async () => {
		await mount(response(), { urgency: 'Cord compression: contact the referrer today.' });
		await expect.element(page.getByRole('alert')).toHaveTextContent('Cord compression');
	});
});
