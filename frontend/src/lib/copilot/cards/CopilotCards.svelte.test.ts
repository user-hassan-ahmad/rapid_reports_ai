// CopilotCards (Task A5). SYNTHETIC fixtures; the Copilot API is mocked and must never be called (presentational).
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';

const api = vi.hoisted(() => ({ postMatch: vi.fn(), postMatchOther: vi.fn(), postOpen: vi.fn(), postPreview: vi.fn() }));
vi.mock('$lib/copilot/api', async (orig) => ({ ...(await orig<object>()), ...api }));

const { default: CopilotCards } = await import('./CopilotCards.svelte');
const { card, outcome, preview, reference, result } = await import('./fixtures');
const { cardRef, groupCards } = await import('../state');
type CardView = import('./view').CardView;
type Card = import('../types').Card;
type Group = import('../state').Group;

const finding = { id: 'u1', unitId: 1, text: 'Solid pulmonary nodule', region: 'LUNGS' };
const exam = card({ key: 'cad-rads-2', name: 'CAD-RADS 2.0', version: '2.0', finding_id: 'exam', finding: 'Coronary CT' });
const v = (r: ReturnType<typeof result> | null, over: Partial<CardView> = {}): CardView => ({ open: false, loading: false, error: null, result: r, ...over });

function props(groups: Group[], views: Record<string, CardView>, over: Record<string, unknown> = {}) {
	return {
		groups,
		views,
		matching: false,
		matchFailed: false,
		otherState: 'idle' as const,
		onOpen: vi.fn(),
		onClose: vi.fn(),
		onRetry: vi.fn(),
		onRetryMatch: vi.fn(),
		onOther: vi.fn(),
		...over
	};
}
const single = (c: Card, view: CardView, f: typeof finding | null = finding) => props([{ finding: f, cards: [c] }], { [cardRef(c)]: view });
const text = () => document.querySelector('[data-testid="copilot-cards"]')!.textContent!.replace(/\s+/g, ' ');

beforeEach(() => Object.values(api).forEach((f) => f.mockReset()));

describe('CopilotCards', () => {
	it('quiet exam card: one line "<name> · <outcome>", no header, and the chevron expands the full card', async () => {
		const p = single(exam, v(result(exam, preview({ proposal: outcome({ classification: 'CAD-RADS 0', normal: true }) }))), null);
		render(CopilotCards, p);
		const line = page.getByRole('button', { name: 'CAD-RADS 2.0 · CAD-RADS 0' });
		await expect.element(line).toBeInTheDocument();
		expect(document.querySelector('.cp-group-head')).toBeNull();
		expect(text()).not.toContain('Follow-up as per');
		await line.click();
		await expect.element(page.getByText('Follow-up as per the guideline table.')).toBeInTheDocument();
		expect(line.element().getAttribute('aria-expanded')).toBe('true');
		expect(p.onOpen).not.toHaveBeenCalled();
		expect(Object.values(api).every((f) => !f.mock.calls.length)).toBe(true);
	});

	it('"set by the exam" badge on the exam card when a value was set by the exam', async () => {
		const pv = preview({ proposal: outcome({ classification: 'CAD-RADS 3', normal: false }), settled: [{ input: 'm', value: 'x', quote: '', fact: '', by: 'exam' }] });
		render(CopilotCards, single(exam, v(result(exam, pv)), null));
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
		await expect.element(page.getByText('on these values · CAD-RADS 3')).toBeInTheDocument();
	});

	it('needs-modality: "<name> needs ultrasound to grade", no chevron, and onOpen is never called', async () => {
		const c = card({ key: 'bta-thyroid-u-grading', name: 'BTA U grading', needs_modality: 'US' });
		const p = single(c, v(null));
		render(CopilotCards, p);
		const row = page.getByTestId('cp-needs-modality');
		await expect.element(row).toBeInTheDocument();
		expect(row.element().textContent!.replace(/\s+/g, ' ').trim()).toBe('BTA U grading needs ultrasound to grade');
		expect(row.element().querySelector('svg, button, [role="button"]')).toBeNull();
		await row.click();
		await userEvent.keyboard('{Enter}');
		expect(p.onOpen).not.toHaveBeenCalled();
	});

	it('TNM opens read-only to the summary and criteria; nothing anywhere is named Apply or Calculate', async () => {
		const tnm = card({ key: 'tnm-lung', name: 'TNM 9 · Lung', finding: finding.text });
		const r = result(tnm, null);
		r.entry!.content = { applies_to: '', summary: 'TNM staging summary.', branches: [{ name: 'Staging', rule: '', inputs: [{ id: 't', question: 'T category', options: ['T1', 'T2'] }] }] };
		// every other card kind opened too, with an Apply-able proposal on the pack: still no Apply
		const fl = card({ finding: finding.text });
		const ref2 = card({ key: 'fazekas', name: 'Fazekas scale', finding: finding.text, reference: true });
		render(
			CopilotCards,
			props([{ finding, cards: [tnm, fl, ref2] }], {
				[cardRef(tnm)]: v(r, { open: true }),
				[cardRef(fl)]: v(result(fl, preview()), { open: true }),
				[cardRef(ref2)]: v(result(ref2, null, { reference }), { open: true })
			})
		);
		await expect.element(page.getByText('TNM staging summary.')).toBeInTheDocument();
		await expect.element(page.getByText('T category')).toBeInTheDocument();
		const names = [...document.querySelectorAll('button, [role="button"], input, select, textarea')].map((b) => (b.textContent ?? '').trim());
		expect(names.some((n) => /^(apply|calculate)\b/i.test(n))).toBe(false);
		expect(document.querySelectorAll('input, select, textarea').length).toBe(0);
	});

	it('siblings render as two columns, primary first, neither preselected', async () => {
		const c = card({ finding: finding.text, siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
		const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
		render(
			CopilotCards,
			{ ...single(c, v(null, { open: true, columns: { [c.key]: { loading: false, error: null, result: result(c, preview()) }, [bts.key]: { loading: true, error: null, result: null } } }), finding), siblingLayout: 'columns' as const }
		);
		const heads = page.getByRole('button', { pressed: false }).elements().filter((e) => e.classList.contains('cp-col-head'));
		await expect.element(page.getByRole('button', { name: 'Fleischner 2017', exact: true })).toBeInTheDocument();
		const all = [...document.querySelectorAll('.cp-col-head')];
		expect(all.map((e) => e.textContent)).toEqual(['Fleischner 2017', 'BTS 2015']);
		expect(heads.length).toBe(2);
		expect(all.every((e) => e.getAttribute('aria-pressed') === 'false')).toBe(true);
		expect(document.querySelectorAll('[data-testid="cp-card-loading"]').length).toBe(1);
	});

	it('does_not_apply dims the card and shows the reason with its citation', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ state: 'does_not_apply', proposal: null, exclusion: outcome({ classification: 'Not for patients under 35', citations: [{ title: 'Guideline', page: 2 }] }) });
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByTestId('cp-exclusion')).toHaveTextContent('Not for patients under 35');
		expect(document.querySelector('.gl-card')!.getAttribute('aria-disabled')).toBe('true');
		expect(text()).toContain('Guideline, p. 2');
		expect(text()).toContain('does not apply');
	});

	it('check_first (B0): values read first, then the outcome, then the open questions; eligibility only as an assumed chip', async () => {
		const c = card({ finding: finding.text });
		const r = result(c, preview({
			state: 'check_first',
			proposal: outcome({ classification: 'Benign adenoma', recommendation: 'No further imaging.' }),
			settled: [
				{ input: 'size', value: '2.2 cm', quote: '2.2 cm left adrenal nodule', fact: '', by: '' },
				{ input: 'phase', value: 'unenhanced', quote: '', fact: '', by: 'exam' }
			],
			missing: ['cancer', 'hormones', 'growth'],
			asks: [
				{ input: 'cancer', label: 'Known extra-adrenal cancer', role: 'eligibility' },
				{ input: 'hormones', label: 'Signs of hormone excess', role: 'eligibility' },
				{ input: 'growth', label: 'Growth on prior imaging', role: 'clinical' }
			]
		}));
		r.entry!.content.branches = [{ name: 'Pack', rule: '', inputs: [{ id: 'size', question: 'Size', options: [] }, { id: 'phase', question: 'Phase', options: [] }] }];
		render(CopilotCards, single(c, v(r, { open: true })));
		const chip = page.getByText('⚠ 2 checks assumed');
		await expect.element(chip).toBeInTheDocument();
		expect(chip.element().getAttribute('title')).toContain('Known extra-adrenal cancer');
		expect(text()).not.toContain('check first');
		expect(text()).not.toContain('Some eligibility questions');
		// order: values, outcome, open questions; the eligibility list stays collapsed
		const body = text();
		const at = (s: string) => body.indexOf(s);
		expect(at('Read from the report')).toBeGreaterThan(-1);
		expect(at('2.2 cm')).toBeLessThan(at('Benign adenoma'));
		expect(at('Benign adenoma')).toBeLessThan(at('Growth on prior imaging'));
		await expect.element(page.getByText('Known extra-adrenal cancer')).not.toBeInTheDocument();
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
		// the quote shows on focus
		const quote = page.getByText('“2.2 cm left adrenal nodule”');
		await expect.element(quote).not.toBeVisible();
		(document.querySelector('.cp-val[tabindex]') as HTMLElement).focus();
		await expect.element(quote).toBeVisible();
		// the assumed checks expand on request
		await page.getByRole('button', { name: /Assumed eligible: 2 checks/ }).click();
		await expect.element(page.getByText('Known extra-adrenal cancer')).toBeInTheDocument();
		await expect.element(page.getByText('Signs of hormone excess')).toBeInTheDocument();
	});

	it('the version sits on its own line under the name; the assumed chip stays on the first line', async () => {
		const c = card({ name: 'ESE adrenal incidentaloma', version: '2023', finding: finding.text });
		const pv = preview({ state: 'check_first', missing: ['e'], asks: [{ input: 'e', label: 'Known cancer', role: 'eligibility' }] });
		render(CopilotCards, single(c, v(result(c, pv))));
		await expect.element(page.getByText('2023')).toBeInTheDocument();
		expect(document.querySelector('.gl-subtitle')!.textContent).toBe('2023');
		expect(document.querySelector('.gl-controls')!.textContent).toContain('⚠ 1 check assumed');
		expect(document.querySelector('.gl-controls')!.textContent).not.toContain('2023');
	});

	it('PackCard takes an assumptions list directly (B1 feeds Task 3)', async () => {
		const { default: PackCard } = await import('./PackCard.svelte');
		const c = card({ finding: finding.text });
		render(PackCard, { card: c, view: v(result(c, preview()), { open: true }), assumptions: ['Not pregnant'], onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn() });
		await expect.element(page.getByText('⚠ 1 check assumed')).toBeInTheDocument();
	});

	it('applies with no outcome lists the possible outcomes; degraded shows its note', async () => {
		const c = card({ finding: finding.text });
		render(CopilotCards, single(c, v(result(c, preview({ proposal: null, possible: ['Cat A', 'Cat B'], degraded: true })), { open: true })));
		await expect.element(page.getByText('Possible:')).toBeInTheDocument();
		await expect.element(page.getByText('Cat B')).toBeInTheDocument();
		await expect.element(page.getByText('Some values could not be checked')).toBeInTheDocument();
	});

	it('the head opens and closes through the callbacks, by keyboard too', async () => {
		const c = card({ finding: finding.text });
		const p = single(c, v(result(c, preview())));
		const r = render(CopilotCards, p);
		const head = page.getByRole('button', { name: /Fleischner 2017/ });
		(head.element() as HTMLElement).focus();
		await userEvent.keyboard('{Enter}');
		expect(p.onOpen).toHaveBeenCalledWith(cardRef(c));
		await r.rerender({ views: { [cardRef(c)]: v(result(c, preview()), { open: true }) } });
		await expect.element(page.getByText('Follow-up as per the guideline table.')).toBeInTheDocument();
		await userEvent.keyboard(' ');
		expect(p.onClose).toHaveBeenCalledWith(cardRef(c));
	});

	it('per card: loading skeleton, "Couldn\'t open · Retry", "Still loading · Retry", unavailable note', async () => {
		const a = card({ finding: finding.text });
		const b = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015', finding: finding.text });
		const c = card({ key: 'acr-x', name: 'ACR thing', finding: finding.text });
		const d = card({ key: 'web-x', name: 'A society guide', finding: finding.text, known: false });
		const p = props([{ finding, cards: [a, b, c, d] }], {
			[cardRef(a)]: v(null, { open: true, loading: true }),
			[cardRef(b)]: v(null, { open: true, error: 'timeout' }),
			[cardRef(c)]: v(null, { open: true, error: 'loading' }),
			[cardRef(d)]: v(null, { open: true, error: 'unavailable', fromOther: true })
		});
		render(CopilotCards, p);
		await expect.element(page.getByTestId('cp-card-loading')).toBeInTheDocument();
		expect(text()).toContain("Couldn't open · Retry");
		expect(text()).toContain('Still loading · Retry');
		expect(text()).toContain('Not in the guideline library yet');
		expect(text()).toContain('other');
		await page.getByRole('button', { name: 'Retry' }).first().click();
		expect(p.onRetry).toHaveBeenCalledWith(cardRef(b));
	});

	it('a card reloading with a result keeps the result on screen (no skeleton flicker)', async () => {
		const pv = preview({ proposal: outcome({ classification: 'CAD-RADS 3', normal: false }) });
		render(CopilotCards, single(exam, v(result(exam, pv), { open: true, loading: true }), null));
		await expect.element(page.getByText('Follow-up as per the guideline table.')).toBeInTheDocument();
		expect(document.querySelector('[data-testid="cp-card-loading"]')).toBeNull();
	});

	it('first match in flight shows the skeleton; no cards shows "No guideline applies yet"', async () => {
		const r = render(CopilotCards, props([], {}, { matching: true }));
		await expect.element(page.getByTestId('cp-skeleton')).toBeInTheDocument();
		await r.rerender({ matching: false });
		await expect.element(page.getByText('No guideline applies yet')).toBeInTheDocument();
	});

	it('match failed with no cards: "Couldn\'t check guidelines · Retry" calls onRetryMatch', async () => {
		const p = props([], {}, { matchFailed: true });
		render(CopilotCards, p);
		await expect.element(page.getByText(/Couldn't check guidelines/)).toBeInTheDocument();
		await page.getByRole('button', { name: 'Retry' }).click();
		expect(p.onRetryMatch).toHaveBeenCalledOnce();
	});

	it('the Other guidelines button calls onOther; loading disables it; failed offers a retry', async () => {
		const c = card({ finding: finding.text });
		const p = single(c, v(null));
		const r = render(CopilotCards, p);
		await page.getByRole('button', { name: 'Other guidelines' }).click();
		expect(p.onOther).toHaveBeenCalledOnce();
		await r.rerender({ otherState: 'loading' });
		await expect.element(page.getByRole('button', { name: /Looking for other guidelines/ })).toBeDisabled();
		await r.rerender({ otherState: 'failed' });
		await page.getByRole('button', { name: 'Retry' }).click();
		expect(p.onOther).toHaveBeenCalledTimes(2);
	});

	it('a group whose finding was deleted renders nothing (and an empty group renders nothing)', async () => {
		const gone = card({ key: 'bosniak-renal-cyst', name: 'Bosniak 2019', finding: 'A deleted finding', finding_id: 'u9' });
		const kept = card({ finding: finding.text });
		const groups = [...groupCards([gone, kept], [finding]), { finding: { ...finding, id: 'u7', text: 'Empty' }, cards: [] }];
		render(CopilotCards, props(groups, {}));
		await expect.element(page.getByText('Fleischner 2017')).toBeInTheDocument();
		expect(text()).not.toContain('Bosniak');
		expect(text()).not.toContain('Empty');
		expect(document.querySelectorAll('.cp-group').length).toBe(1);
	});
});
