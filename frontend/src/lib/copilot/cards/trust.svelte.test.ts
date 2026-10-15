// Spec §7.12 on the cards: the not-needed line, the growth exclusion's wording, "Seen, leave as is" and the rail
// revealing a card. SYNTHETIC fixtures; the Copilot API is never called (presentational).
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import '$lib/rail/rail.css';
import { cardRef } from '../state';
import CopilotRail from './CopilotRail.svelte';
import { card, draft, outcome, preview, result } from './fixtures';
import PackBody from './PackBody.svelte';
import PackCard from './PackCard.svelte';
import SiblingColumns from './SiblingColumns.svelte';
import { closedView } from './view';

const handlers = () => ({ onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn() });
const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
const workup = preview({ proposal: outcome({ headline: 'Consider PET-CT', action: 'PET-CT', category: 'workup' }) });

describe('the count tells the truth (§7.12 item 3)', () => {
	it('the head shows "1 question open"; the body a collapsed "4 not needed on this branch" that expands to the labels', async () => {
		const p = preview({
			proposal: null,
			draft: [
				draft({ input: 'growth', label: 'Growth', state: 'asked', needed: true }),
				draft({ input: 'age', label: 'Age', state: 'asked' }),
				draft({ input: 'smoking', label: 'Smoking history', state: 'asked' }),
				draft({ input: 'family', label: 'Family history', state: 'asked' }),
				draft({ input: 'emphysema', label: 'Emphysema', state: 'asked' })
			]
		});
		render(PackCard, { card: bts, view: { ...closedView, open: true, result: result(bts, p) }, ...handlers() });
		await expect.element(page.getByText('1 question open')).toBeInTheDocument();
		await page.getByRole('button', { name: /^(All values used|Hide values)/ }).click(); // the not-needed line lives in the "Based on" region
		const toggle = page.getByRole('button', { name: '4 not needed on this branch' });
		await expect.element(toggle).toHaveAttribute('aria-expanded', 'false');
		await expect.element(page.getByText('Smoking history')).not.toBeVisible();
		await expect.element(page.getByText('Growth', { exact: true })).toBeVisible(); // the needed one stays in the list
		await toggle.click();
		for (const l of ['Age', 'Smoking history', 'Family history', 'Emphysema']) await expect.element(page.getByText(l, { exact: true })).toBeVisible();
	});
});

describe('an exclusion worded by its outcome (§7.12 item 1)', () => {
	it('leads with the outcome headline and shows its action', async () => {
		const p = preview({
			state: 'does_not_apply',
			proposal: null,
			exclusion: outcome({ headline: 'Outside the table: interval growth', recommendation: 'The table covers new findings. See the other card.', classification: 'Does not apply: grown.', category: 'not_applicable' }),
			exclusion_reason: { input: 'prior_growth', label: 'Earlier imaging shows growth', value: 'Yes', outcome: 'outside_table_growth' }
		});
		render(PackBody, { result: result(bts, p), expanded: true, onExpand: vi.fn() }); // an exclusion collapses to one row by default
		await expect.element(page.getByText('Outside the table: interval growth')).toBeInTheDocument();
		await expect.element(page.getByText('The table covers new findings. See the other card.')).toBeInTheDocument();
	});
});

describe('"Seen, leave as is" (§7.12 item 5)', () => {
	it('an unresolved card shows its reason and "Seen, leave as is"; clicking calls seen(key)', async () => {
		const onSeen = vi.fn();
		const key = cardRef(bts);
		render(PackCard, {
			card: bts,
			view: { ...closedView, open: true, result: result(bts, workup) },
			unresolved: { key, card: key, name: 'BTS 2015', reason: 'Conclusion gives follow-up imaging; BTS 2015 says further tests' },
			onSeen,
			...handlers()
		});
		await expect.element(page.getByText('Conclusion gives follow-up imaging; BTS 2015 says further tests')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Not in this report' }).click();
		expect(onSeen).toHaveBeenCalledWith(key);
	});

	it('a resolved card offers no "Seen"', async () => {
		render(PackCard, { card: bts, view: { ...closedView, open: true, result: result(bts, workup) }, onSeen: vi.fn(), ...handlers() });
		await expect.element(page.getByText('Consider PET-CT')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Not in this report' })).not.toBeInTheDocument();
	});

	it('a sibling column that is unresolved carries its own "Seen", keyed by its column ref', async () => {
		const onSeen = vi.fn();
		const fl = card({ siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
		const key = `${cardRef(fl)}#bts-pulmonary-nodule`;
		const columns = {
			'fleischner-pulmonary-nodule': { loading: false, error: null, result: result(fl, preview()) },
			'bts-pulmonary-nodule': { loading: false, error: null, result: result(bts, workup) }
		};
		render(SiblingColumns, {
			card: fl,
			view: { ...closedView, open: true, columns },
			layout: 'stacked',
			unresolved: { [key]: { key, card: cardRef(fl), name: 'BTS 2015' } },
			onSeen,
			...handlers()
		});
		const seen = page.getByRole('button', { name: 'Not in this report' });
		await expect.element(seen).toBeInTheDocument();
		expect(seen.elements()).toHaveLength(1);
		await seen.click();
		expect(onSeen).toHaveBeenCalledWith(key);
	});
});

describe('the rail reveals a card by key', () => {
	it('opens the card (narrow: the overlay too) and scrolls it into view', async () => {
		const scroll = vi.fn();
		const orig = Element.prototype.scrollIntoView;
		Element.prototype.scrollIntoView = scroll;
		try {
			const f = { id: 'u1', unitId: 1, text: 'Solid pulmonary nodule', region: 'LUNGS' };
			const c = card({ finding: f.text });
			const onOpen = vi.fn();
			const r = render(CopilotRail, {
				layout: 'narrow',
				groups: [{ finding: f, cards: [c] }],
				views: {},
				matching: false,
				matchFailed: false,
				otherState: 'idle' as const,
				onOpen,
				onClose: vi.fn(),
				onRetry: vi.fn(),
				onRetryMatch: vi.fn(),
				onOther: vi.fn()
			});
			await (r.component as unknown as { reveal(ref: string): Promise<void> }).reveal(cardRef(c));
			expect(onOpen).toHaveBeenCalledWith(cardRef(c));
			await expect.element(page.getByRole('dialog', { name: 'Copilot' })).toBeInTheDocument();
			expect(scroll).toHaveBeenCalled();
			expect((scroll.mock.contexts[0] as HTMLElement).getAttribute('data-ref')).toBe(cardRef(c));
		} finally {
			Element.prototype.scrollIntoView = orig;
		}
	});
});
