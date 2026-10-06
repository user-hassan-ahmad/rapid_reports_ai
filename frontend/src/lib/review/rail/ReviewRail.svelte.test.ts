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
	it('groups rows by section in report order, Unanchored last; checks, options and normals are not in sections', async () => {
		await mount();
		await expect.element(page.getByRole('heading', { name: 'Liver' })).toBeInTheDocument();
		const headings = [...rail()!.querySelectorAll('[data-rv-section]')].map((h) =>
			h.getAttribute('data-rv-section')
		);
		expect(headings).toEqual(['Liver', 'Spleen', 'Kidneys', 'Unanchored']);
		const liver = rail()!.querySelector('[data-rv-section="Liver"]')!.closest('section')!;
		const ids = [...liver.querySelectorAll('[data-rv-item]')].map((e) =>
			e.getAttribute('data-rv-item')
		);
		expect(ids).toEqual(['i1', 'm1']); // by anchor start; c1 (check) and n1 (normal) excluded
		expect(rail()!.querySelector('[data-rv-item="n1"]')).toBeNull();
		expect(rail()!.textContent).not.toContain('Liver normal');
	});

	it('renders by class: action card, minor row, info tag, and the pre-applied variants', async () => {
		await mount();
		await expect.element(page.getByText('Measurement differs')).toBeInTheDocument();
		expect(rail()!.querySelector('[data-rv-item="a1"]')!.getAttribute('data-rv-variant')).toBe(
			'card'
		);
		expect(rail()!.querySelector('[data-rv-item="m1"]')!.getAttribute('data-rv-variant')).toBe(
			'row'
		);
		expect(rail()!.querySelector('[data-rv-item="i1"]')!.getAttribute('data-rv-variant')).toBe(
			'tag'
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

	it('shows checks as one "N to check" group, collapsed by default, with Keep and Remove', async () => {
		const { onCommand } = await mount();
		const toggle = page.getByRole('button', { name: /2 to check/ });
		await expect.element(toggle).toBeInTheDocument();
		await expect.element(toggle).toHaveAttribute('aria-expanded', 'false');
		expect(rail()!.querySelector('[data-rv-item="c1"]')).toBeNull();
		await toggle.click();
		await expect.element(toggle).toHaveAttribute('aria-expanded', 'true');
		const c1 = rail()!.querySelector<HTMLElement>('[data-rv-item="c1"]')!;
		expect(c1.closest('[data-rv-group="checks"]')).not.toBeNull();
		await page.getByRole('button', { name: 'Keep: No hydronephrosis' }).click();
		expect(onCommand).toHaveBeenCalledWith('keep', 'c1');
		await page.getByRole('button', { name: 'Remove: Spleen 12 cm' }).click();
		expect(onCommand).toHaveBeenCalledWith('remove', 'c2');
		await toggle.click();
		await expect.element(toggle).toHaveAttribute('aria-expanded', 'false');
		expect(rail()!.querySelector('[data-rv-item="c1"]')).toBeNull();
	});

	it('shows options in an Options group with Add', async () => {
		const { onCommand } = await mount();
		const group = rail()!.querySelector('[data-rv-group="options"]');
		expect(group).not.toBeNull();
		expect(group!.textContent).toContain('No free fluid');
		await page.getByRole('button', { name: 'Add: No free fluid' }).click();
		expect(onCommand).toHaveBeenCalledWith('apply', 'o1');
	});

	it('folds suppressed and dismissed items into "N other checks passed"', async () => {
		await mount();
		const fold = page.getByRole('button', { name: /2 other checks passed/ });
		await expect.element(fold).toBeInTheDocument();
		expect(rail()!.textContent).not.toContain('dismissed one');
		await fold.click();
		await expect.element(page.getByText('dismissed one')).toBeInTheDocument();
	});

	it('Apply on a card calls the command callback; clicking a row opens the item', async () => {
		const { onCommand } = await mount();
		await page.getByRole('button', { name: 'Apply: Measurement differs' }).click();
		expect(onCommand).toHaveBeenCalledWith('apply', 'a1');
		await page.getByRole('button', { name: 'Open: Tidy wording' }).click();
		expect(onCommand).toHaveBeenCalledWith('open_item', 'm1');
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
		const extra = item({
			id: 'a2',
			kind: 'measurement',
			cls: 'action',
			section: 'Liver',
			label: 'Late action',
			anchor: at(90),
			edit: { mode: 'replace', find: 'x', replace: 'z' }
		});
		await mount(response({ items: [...ITEMS, extra] }));
		await expect.element(page.getByText('Late action')).toBeInTheDocument();
		const liver = rail()!.querySelector('[data-rv-section="Liver"]')!.closest('section')!;
		const ids = [...liver.querySelectorAll('[data-rv-item]')].map((e) => e.getAttribute('data-rv-item'));
		expect(ids).toEqual(['a2', 'i1', 'm1']);
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
		expect(rail()!.querySelector('[data-rv-legend]')!.textContent).toContain('Assumed normal');
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
		await mount(response(), { updating: new Set(['m1']) });
		const m1 = rail()!.querySelector<HTMLElement>('[data-rv-item="m1"]')!;
		expect(m1.textContent).toContain('updating…');
	});

	it('collapses to a strip with the open count when narrow, opening as an overlay', async () => {
		await mount(response(), { layout: 'narrow' });
		// open = open action + minor rows: a1, m1, u1, c1, c2, o1
		const strip = page.getByRole('button', { name: /6 open/ });
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

	it('reveal (the chip ›) opens the collapsed checks group, scrolls to the card, highlights and focuses it', async () => {
		const { screen, store, onCommand } = await mount();
		expect(rail()!.querySelector('[data-rv-item="c2"]')).toBeNull(); // collapsed
		await screen.rerender({ store, onCommand, layout: 'wide', reveal: { id: 'c2', seq: 1 } });
		await expect.element(page.getByText('Spleen 12 cm')).toBeInTheDocument();
		const card = rail()!.querySelector<HTMLElement>('[data-rv-item="c2"]')!;
		await expect.poll(() => card.classList.contains('rv-revealed')).toBe(true);
		expect(card.contains(document.activeElement)).toBe(true);
	});

	it('shows an urgency banner at the top', async () => {
		await mount(response(), { urgency: 'Cord compression: contact the referrer today.' });
		await expect.element(page.getByRole('alert')).toHaveTextContent('Cord compression');
	});
});
