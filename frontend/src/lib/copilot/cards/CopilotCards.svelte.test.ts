// CopilotCards (Task A5). SYNTHETIC fixtures; the Copilot API is mocked and must never be called (presentational).
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';

const api = vi.hoisted(() => ({ postMatch: vi.fn(), postMatchOther: vi.fn(), postOpen: vi.fn(), postPreview: vi.fn() }));
vi.mock('$lib/copilot/api', async (orig) => ({ ...(await orig<object>()), ...api }));

const { default: CopilotCards } = await import('./CopilotCards.svelte');
const { card, draft, outcome, preview, reference, result } = await import('./fixtures');
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
		const line = page.getByRole('button', { name: /CAD-RADS 2\.0.*CAD-RADS 0/ });
		await expect.element(line).toBeInTheDocument();
		expect(document.querySelector('.cp-group-head')).toBeNull();
		expect(text()).not.toContain('Follow-up as per');
		await line.click();
		await expect.element(page.getByText('Follow-up as per the guideline table').first()).toBeInTheDocument();
		expect(line.element().getAttribute('aria-expanded')).toBe('true');
		expect(p.onOpen).not.toHaveBeenCalled();
		expect(Object.values(api).every((f) => !f.mock.calls.length)).toBe(true);
	});

	it('"set by the exam" badge on the exam card when a value was set by the exam', async () => {
		const pv = preview({ proposal: outcome({ classification: 'CAD-RADS 3', normal: false }), settled: [{ input: 'm', value: 'x', quote: '', fact: '', by: 'exam' }] });
		render(CopilotCards, single(exam, v(result(exam, pv)), null));
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
		// the verdict pill: the action (the recommendation's first sentence until the backend sends one)
		await expect.element(page.getByText('Follow-up as per the guideline table', { exact: true })).toBeInTheDocument();
		expect(document.querySelector('.cp-pill')!.textContent).toContain('Follow-up as per the guideline table');
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
		expect(text()).toContain('Guideline, p. 2'); // the full source, behind its one-line summary
		expect(document.querySelector('.cp-pill')!.textContent).toContain('Does not apply');
		expect(document.querySelector('.cp-pill')!.getAttribute('data-category')).toBe('not_applicable');
	});

	it('check_first: the verdict first, then the values, then the open questions; eligibility only as an assumed chip', async () => {
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
		const chip = page.getByText('⚠ 2 assumed');
		await expect.element(chip).toBeInTheDocument();
		expect(chip.element().getAttribute('title')).toContain('Known extra-adrenal cancer');
		// screen readers get the checks in the head's name, not only from the tooltip
		expect(chip.element().querySelector('.cp-sr-only')!.textContent).toContain('Known extra-adrenal cancer; Signs of hormone excess');
		expect(chip.element().closest('[role="button"]')!.textContent).toContain('assumed eligibility checks: Known extra-adrenal cancer');
		expect(text()).not.toContain('check first');
		expect(text()).not.toContain('Some eligibility questions');
		// order in the body: the verdict, then the values, then the open questions; the eligibility list stays collapsed
		const body = document.querySelector('.gl-body')!.textContent!;
		const at = (s: string) => body.indexOf(s);
		expect(at('Benign adenoma')).toBeLessThan(at('Values'));
		expect(at('Values')).toBeLessThan(at('2.2 cm'));
		expect(at('2.2 cm')).toBeLessThan(at('Growth on prior imaging'));
		const toggle = page.getByRole('button', { name: /Assumed eligible: 2 checks/ });
		const list = document.getElementById(toggle.element().getAttribute('aria-controls')!)!;
		expect(list.hidden).toBe(true); // in the DOM, collapsed
		expect(toggle.element().getAttribute('aria-expanded')).toBe('false');
		await expect.element(page.getByText('set by the exam').first()).toBeInTheDocument();
		// the quote shows on focus
		const quote = page.getByText('“2.2 cm left adrenal nodule”');
		await expect.element(quote).not.toBeVisible();
		const row = document.querySelector('.cp-val[tabindex]') as HTMLElement;
		expect(document.getElementById(row.getAttribute('aria-describedby')!)!.textContent!.trim()).toBe('“2.2 cm left adrenal nodule”');
		row.focus();
		await expect.element(quote).toBeVisible();
		// the assumed checks expand on request, by keyboard
		(toggle.element() as HTMLElement).focus();
		await userEvent.keyboard('{Enter}');
		expect(toggle.element().getAttribute('aria-expanded')).toBe('true');
		expect(list.hidden).toBe(false);
		expect(list.textContent).toContain('Signs of hormone excess');
	});

	it('Task 3 draft card: draft_outcome verdict, then values, then Still open; assumed under the chip; waiting hidden; no Apply', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({
			state: 'check_first',
			proposal: null,
			draft_outcome: outcome({ classification: 'Benign adenoma', recommendation: 'No further imaging.' }),
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm nodule' }),
				draft({ input: 'hu', label: 'Unenhanced HU', state: 'prefilled', value: '8 HU', quote: '8 HU', why: ['attenuation not stated as unenhanced'] }),
				draft({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No' }),
				draft({ input: 'growth', label: 'Growth on prior imaging', state: 'asked', needed: true }),
				draft({ input: 'rate', label: 'Growth rate', state: 'asked', waiting: true })
			],
			assumptions: ['cancer'],
			assumed_eligible: true
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByText('⚠ 1 assumed')).toBeInTheDocument();
		const body = document.querySelector('.gl-body')!.textContent!;
		const at = (x: string) => body.indexOf(x);
		expect(at('Benign adenoma')).toBeLessThan(at('2.2 cm'));
		expect(at('2.2 cm')).toBeLessThan(at('Growth on prior imaging'));
		expect(body).toContain('On these values');
		expect(body).not.toContain('Growth rate'); // waiting: hidden
		expect(document.querySelector('.cp-prefill')!.textContent).toBe('8 HU');
		const toggle = page.getByRole('button', { name: /Assumed eligible: 1 check/ });
		await toggle.click();
		expect(document.getElementById(toggle.element().getAttribute('aria-controls')!)!.textContent).toContain('Known cancer: No');
		const names = [...document.querySelectorAll('button, [role="button"]')].map((b) => (b.textContent ?? '').trim());
		expect(names.some((n) => /^(apply|calculate)\b/i.test(n))).toBe(false);
		expect(document.querySelectorAll('input, select, textarea').length).toBe(0);
	});

	it('the quiet exam line follows draft_outcome.normal (proposal is always null for packs)', async () => {
		const quietPv = preview({ proposal: null, draft_outcome: outcome({ classification: 'CAD-RADS 0', normal: true }) });
		const r = render(CopilotCards, single(exam, v(result(exam, quietPv)), null));
		await expect.element(page.getByRole('button', { name: /CAD-RADS 2\.0.*CAD-RADS 0/ })).toBeInTheDocument();
		await r.rerender({ views: { [cardRef(exam)]: v(result(exam, preview({ proposal: null, draft_outcome: outcome({ classification: 'CAD-RADS 3', normal: false }) }))) } });
		await expect.element(page.getByText('Follow-up as per the guideline table', { exact: true })).toBeInTheDocument(); // a full card's pill
		expect(document.querySelector('[data-testid="cp-quiet"]')).toBeNull();
	});

	it('a quiet normal exam line resting on assumed checks shows the accessible "⚠ N checks assumed" cue', async () => {
		const pv = preview({
			proposal: null,
			draft_outcome: outcome({ classification: 'CAD-RADS 0', normal: true }),
			draft: [draft({ input: 'symptoms', label: 'Stable symptoms', role: 'eligibility', state: 'assumed', value: 'Yes' })],
			assumptions: ['symptoms'],
			assumed_eligible: true
		});
		render(CopilotCards, single(exam, v(result(exam, pv)), null));
		await expect.element(page.getByRole('button', { name: /CAD-RADS 2\.0.*CAD-RADS 0/ })).toBeInTheDocument(); // still one line
		const chip = page.getByRole('button', { name: /1 assumed/ });
		await expect.element(chip).toHaveAttribute('aria-expanded', 'false');
		// the list is in the button's text for screen readers (visually hidden), not only in a tooltip
		expect(chip.element().querySelector('.cp-sr-only')!.textContent).toBe(' eligibility check: Stable symptoms: Yes');
		const list = document.getElementById(chip.element().getAttribute('aria-controls')!)!;
		expect(list.hidden).toBe(true);
		(chip.element() as HTMLElement).focus();
		await userEvent.keyboard('{Enter}');
		await expect.element(chip).toHaveAttribute('aria-expanded', 'true');
		expect(list.hidden).toBe(false);
		expect(list.textContent).toContain('Stable symptoms: Yes');
	});

	it('a quiet line with assumed_eligible but no assumed rows still shows a cue', async () => {
		const pv = preview({ proposal: null, draft_outcome: outcome({ classification: 'CAD-RADS 0', normal: true }), assumed_eligible: true });
		render(CopilotCards, single(exam, v(result(exam, pv)), null));
		await expect.element(page.getByRole('button', { name: /⚠\s*assumed/ })).toBeInTheDocument();
	});

	it('head: name and verdict pill on the first line; value chips and the assumed cue on the second', async () => {
		const c = card({ name: 'ESE adrenal incidentaloma', version: '2023', finding: finding.text });
		const pv = preview({
			state: 'check_first',
			proposal: null,
			draft_outcome: outcome({ classification: 'Benign: lipid-rich adenoma', recommendation: 'No further imaging required.', category: 'none' }),
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm' }),
				draft({ input: 'hu', label: 'HU', state: 'prefilled', value: '8 HU', why: ['x'] }),
				draft({ input: 'homog', label: 'Homogeneous', state: 'read', value: 'Yes', quote: 'homogeneous' }),
				draft({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No' })
			]
		});
		render(CopilotCards, single(c, v(result(c, pv))));
		const titleRow = document.querySelector('.gl-title-row')!;
		await expect.element(page.getByText('No further imaging required', { exact: true })).toBeInTheDocument();
		expect(titleRow.textContent).toContain('ESE adrenal incidentaloma');
		expect(titleRow.querySelector('.cp-pill')!.getAttribute('data-category')).toBe('none');
		const second = document.querySelector('.cp-headchips')!;
		expect([...second.querySelectorAll('.cp-vchip')].map((e) => e.textContent!.trim())).toEqual(['2.2 cm', '8 HU', 'Homogeneous']); // assumed: only the ⚠ chip
		expect(second.querySelector('.cp-vchip--prefilled')!.textContent!.trim()).toBe('8 HU');
		expect(second.textContent).toContain('⚠ 1 assumed');
		// the card's left strip takes the category colour
		expect((document.querySelector('.gl-card') as HTMLElement).style.getPropertyValue('--gl-accent')).toBe('var(--rv-green-line)');
	});

	it('ESE benign (checkpoint 3): verdict, then "5 notes" and ONE source line, each expandable by keyboard', async () => {
		const c = card({ name: 'ESE adrenal incidentaloma', finding: finding.text });
		const src = { title: 'ESE guidelines on adrenal incidentalomas', issuer: 'European Society of Endocrinology', edition: '2023' };
		const long = 'Homogeneous adrenal mass of 10 HU or less on unenhanced CT: consistent with a benign (lipid-rich) lesion, whatever its size.';
		const pv = preview({
			proposal: null,
			draft_outcome: outcome({
				classification: long,
				recommendation: 'No further imaging required.',
				headline: 'Benign adrenal adenoma',
				action: 'No further imaging',
				category: 'none',
				caveats: ['Note one is long enough to clamp in a narrow rail column for sure.', 'Note two.', 'Note three.', 'Note four.', 'Note five.'],
				citations: [{ ...src, page: 18, section: 'Figure 5' }, { ...src, page: 17, section: 'Figure 4' }, { ...src, page: 18, section: 'Figure 5' }]
			})
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		const verdict = page.getByRole('region', { name: 'Verdict' });
		await expect.element(verdict).toHaveTextContent('Benign adrenal adenoma');
		expect(verdict.element().textContent).toContain('No further imaging');
		// the classification is there in full, clamped, with "more"
		const more = page.getByRole('button', { name: 'more' });
		await expect.element(more).toHaveAttribute('aria-expanded', 'false');
		const cls = document.getElementById(more.element().getAttribute('aria-controls')!)!;
		expect(cls.classList.contains('cp-clamp')).toBe(true);
		await more.click();
		await expect.element(page.getByRole('button', { name: 'less' })).toHaveAttribute('aria-expanded', 'true');
		expect(cls.classList.contains('cp-clamp')).toBe(false);
		// notes: one line, collapsed
		const notes = page.getByRole('button', { name: /5 notes/ });
		const noteList = document.getElementById(notes.element().getAttribute('aria-controls')!)!;
		expect(noteList.hidden).toBe(true);
		(notes.element() as HTMLElement).focus();
		await userEvent.keyboard('{Enter}');
		expect(noteList.hidden).toBe(false);
		const first = page.getByRole('button', { name: /Note one/ });
		await expect.element(first).toHaveAttribute('aria-expanded', 'false');
		await first.click();
		await expect.element(first).toHaveAttribute('aria-expanded', 'true');
		// source: one short line for two distinct citations (identical ones merged), the full list on request
		const source = page.getByRole('button', { name: /ESE 2023 · Fig 5, p\. 18/ });
		await expect.element(source).toHaveTextContent('+1');
		const srcList = document.getElementById(source.element().getAttribute('aria-controls')!)!;
		expect(srcList.hidden).toBe(true);
		expect(srcList.querySelectorAll('li')).toHaveLength(2);
		await source.click();
		expect(srcList.hidden).toBe(false);
	});

	it('no outcome yet: "Most likely" (category-coloured, under assumptions), "Depends on" with at most three branches, "show all"', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({
			proposal: null,
			most_likely: { headline: 'CT surveillance', category: 'surveillance' },
			deciding_input: 'brock',
			deciding: [
				{ answer: '< 10%', headline: 'CT surveillance', category: 'surveillance' },
				{ answer: '10–70%', headline: 'PET-CT', category: 'workup' },
				{ answer: '> 70%', headline: 'Biopsy', category: 'refer' },
				{ answer: 'unknown', headline: 'Fourth branch', category: 'info' }
			],
			possible: ['a', 'b', 'c', 'd', 'e'],
			draft: [draft({ input: 'brock', label: 'Brock risk', state: 'asked', needed: true }), draft({ input: 'adult', label: 'Adult', role: 'eligibility', state: 'assumed', value: 'Yes' })],
			assumed_eligible: true
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByText('CT surveillance', { exact: true }).first()).toBeInTheDocument();
		const likely = page.getByRole('region', { name: 'Most likely' }).element();
		expect(likely.textContent).toContain('Most likely: CT surveillance');
		expect(likely.textContent).toContain('under assumptions');
		expect(likely.textContent).toContain('Depends on Brock risk');
		expect(likely.querySelectorAll('.cp-branches li')).toHaveLength(3);
		expect(likely.textContent).not.toContain('Fourth branch');
		expect(document.querySelector('.cp-pill')!.textContent).toContain('Likely: CT surveillance');
		expect(document.querySelector('.cp-pill')!.classList.contains('cp-pill--tentative')).toBe(true);
		const all = page.getByRole('button', { name: 'show all 5' });
		const list = document.getElementById(all.element().getAttribute('aria-controls')!)!;
		expect(list.hidden).toBe(true);
		await all.click();
		expect(list.hidden).toBe(false);
		expect(document.body.textContent).not.toContain('outcomes still possible');
	});

	it('B2: with onEdit, a still-open question is answered in place, an assumed value can be changed; Calculate calls back; no Apply', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({
			proposal: null,
			draft_outcome: outcome({ classification: 'Benign: x', recommendation: 'No further imaging.' }),
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm' }),
				draft({ input: 'brock', label: 'Brock risk', state: 'asked', needed: true, options: ['Under 10%', '10% or more', 'Not stated'] }),
				draft({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No', options: ['Yes', 'No', 'Not stated'] })
			]
		});
		const p = { ...single(c, v(result(c, pv), { open: true })), onEdit: vi.fn(), onCalculate: vi.fn() };
		render(CopilotCards, p);
		await page.getByRole('button', { name: 'Answer Brock risk' }).click();
		await page.getByRole('combobox', { name: 'Answer for Brock risk' }).selectOptions('Under 10%');
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'brock', 'Under 10%');
		await page.getByRole('button', { name: /Assumed eligible/ }).click();
		await page.getByRole('button', { name: 'Change Known cancer' }).click();
		await page.getByRole('combobox', { name: 'Answer for Known cancer' }).selectOptions('Yes');
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'cancer', 'Yes');
		await page.getByRole('button', { name: 'Calculate' }).click();
		expect(p.onCalculate).toHaveBeenCalledWith(cardRef(c));
		const names = [...document.querySelectorAll('button, [role="button"]')].map((b) => (b.textContent ?? '').trim());
		expect(names.some((n) => /^apply\b/i.test(n))).toBe(false);
	});

	it('B2: a Calculate result shows the outcome, the values used with their state, and still-assumed values', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, draft_outcome: outcome(), draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm' })] });
		const calc = {
			loading: false,
			error: null,
			result: {
				outcome: 'benign',
				result: outcome({ classification: 'Benign lipid-rich adenoma: no work-up', recommendation: 'No further imaging.' }),
				exclusion: null,
				possible: [],
				needed: [],
				values: [
					draft({ input: 'size', label: 'Size', state: 'edited', value: '2.4 cm' }),
					draft({ input: 'cancer', label: 'Known cancer', state: 'assumed', value: 'No' })
				],
				assumptions: ['cancer'],
				trace: null,
				pack: 'p@1',
				bundle: 'b'
			}
		};
		render(CopilotCards, { ...single(c, v(result(c, pv), { open: true, calc })), onEdit: vi.fn(), onCalculate: vi.fn() });
		const region = page.getByRole('region', { name: 'Calculated' });
		await expect.element(region).toHaveTextContent('Calculated on these values');
		const t = region.element().textContent!;
		expect(t).toContain('Benign lipid-rich adenoma');
		expect(t).toContain('No further imaging');
		expect(t).toContain('1 value is still assumed (Known cancer): confirmed only at Apply');
		const used = [...region.element().querySelectorAll('.cp-calc-values li')].map((li) => li.textContent!.replace(/\s+/g, ' ').trim());
		expect(used).toEqual(['Size 2.4 cm changed', 'Known cancer No assumed']);
	});

	it('B2: a Calculate with no outcome lists what is still needed and the possible outcomes; an exclusion reads "Does not apply"', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, draft: [draft({ input: 'brock', label: 'Brock risk', state: 'asked', needed: true })] });
		const base = { outcome: null, result: null, exclusion: null, values: [], assumptions: [], trace: null, pack: 'p@1', bundle: 'b' };
		const r = render(CopilotCards, { ...single(c, v(result(c, pv), { open: true, calc: { loading: false, error: null, result: { ...base, possible: ['CT surveillance', 'PET-CT'], needed: ['brock'] } } })), onCalculate: vi.fn() });
		const region = page.getByRole('region', { name: 'Calculated' });
		await expect.element(region).toHaveTextContent('Not enough to decide');
		expect(region.element().textContent).toContain('Still needed: Brock risk');
		expect(region.element().textContent).toContain('2 outcomes possible: CT surveillance; PET-CT');
		await r.rerender({ views: { [cardRef(c)]: v(result(c, pv), { open: true, calc: { loading: false, error: null, result: { ...base, possible: [], needed: [], exclusion: outcome({ classification: 'Not for under 35s' }) } } }) } });
		await expect.element(page.getByRole('region', { name: 'Calculated' })).toHaveTextContent('Does not apply');
	});

	it('B2: Calculate is disabled while the card re-previews; a failed edit shows its note', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, draft_outcome: outcome(), draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm' })] });
		const r = render(CopilotCards, { ...single(c, v(result(c, pv), { open: true, loading: true })), onEdit: vi.fn(), onCalculate: vi.fn() });
		await expect.element(page.getByRole('button', { name: 'Calculate' })).toBeDisabled();
		await expect.element(page.getByText('updating the card…')).toBeInTheDocument();
		await r.rerender({ views: { [cardRef(c)]: v(result(c, pv), { open: true, editError: "Couldn't apply that change; it was undone" }) } });
		await expect.element(page.getByRole('alert')).toHaveTextContent('it was undone');
		await expect.element(page.getByRole('button', { name: 'Calculate' })).toBeEnabled();
	});

	it('PackCard takes an assumptions list directly (B1 feeds Task 3)', async () => {
		const { default: PackCard } = await import('./PackCard.svelte');
		const c = card({ finding: finding.text });
		render(PackCard, { card: c, view: v(result(c, preview()), { open: true }), assumptions: ['Not pregnant'], onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn() });
		await expect.element(page.getByText('⚠ 1 assumed')).toBeInTheDocument();
	});

	it('no outcome: "Still open" first, then one collapsed "N outcomes still possible" line; degraded shows its note', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, possible: ['Cat A', 'Cat B', 'Cat C'], missing: ['growth'], asks: [{ input: 'growth', label: 'Growth', role: 'clinical' }], degraded: true });
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		const toggle = page.getByRole('button', { name: '3 outcomes still possible — show' });
		await expect.element(toggle).toBeInTheDocument();
		await expect.element(page.getByText('Cat B')).not.toBeVisible();
		expect(text().indexOf('Still open')).toBeLessThan(text().indexOf('outcomes still possible'));
		(toggle.element() as HTMLElement).focus();
		await userEvent.keyboard('{Enter}');
		await expect.element(page.getByText('Cat B')).toBeVisible();
		await expect.element(page.getByRole('button', { name: '3 outcomes still possible — hide' })).toHaveAttribute('aria-expanded', 'true');
		await expect.element(page.getByText('Some values could not be checked')).toBeInTheDocument();
	});

	it('with a proposal only the proposal shows (no possible list); a single possible outcome shows inline', async () => {
		const c = card({ finding: finding.text });
		const r = render(CopilotCards, single(c, v(result(c, preview({ possible: ['Cat A', 'Cat B'] })), { open: true })));
		await expect.element(page.getByText('Category A')).toBeInTheDocument();
		expect(text()).not.toContain('still possible');
		await r.rerender({ views: { [cardRef(c)]: v(result(c, preview({ proposal: null, possible: ['Only one'] })), { open: true }) } });
		await expect.element(page.getByText('Only one')).toBeVisible();
	});

	it('a check_first card with nothing missing still shows a visible "check first" cue', async () => {
		const c = card({ finding: finding.text });
		render(CopilotCards, single(c, v(result(c, preview({ state: 'check_first', missing: [] })))));
		await expect.element(page.getByText('⚠ check first')).toBeVisible();
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
		await expect.element(page.getByText('Follow-up as per the guideline table').first()).toBeInTheDocument();
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
		await expect.element(page.getByText('Follow-up as per the guideline table').first()).toBeInTheDocument();
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
