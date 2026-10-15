// CopilotCards (Task A5). SYNTHETIC fixtures; the Copilot API is mocked and must never be called (presentational).
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';

const api = vi.hoisted(() => ({ postMatch: vi.fn(), postMatchOther: vi.fn(), postOpen: vi.fn(), postPreview: vi.fn() }));
vi.mock('$lib/copilot/api', async (orig) => ({ ...(await orig<object>()), ...api }));

const { default: CopilotCards } = await import('./CopilotCards.svelte');
const { assumption, card, draft, outcome, preview, reference, result } = await import('./fixtures');
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
	it('quiet exam card: one line (name + grade pill), no header; the chevron expands the full card', async () => {
		const p = single(exam, v(result(exam, preview({ proposal: outcome({ classification: 'CAD-RADS 0', normal: true }) }))), null);
		render(CopilotCards, p);
		const line = page.getByRole('button', { name: /CAD-RADS 2\.0.*CAD-RADS 0/ });
		await expect.element(line).toBeInTheDocument();
		expect(document.querySelector('.cp-group-head')).toBeNull();
		expect(document.querySelector('.cp-verdict')).toBeNull();
		await line.click();
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toHaveTextContent('CAD-RADS 0');
		expect(line.element().getAttribute('aria-expanded')).toBe('true');
		expect(p.onOpen).not.toHaveBeenCalled();
		expect(Object.values(api).every((f) => !f.mock.calls.length)).toBe(true);
	});

	it('"set by the exam" shows as the provenance of the exam-set value; the pill carries the action', async () => {
		const pv = preview({ proposal: outcome({ classification: 'CAD-RADS 3', normal: false }), settled: [{ input: 'm', value: 'x', quote: '', fact: '', by: 'exam' }] });
		render(CopilotCards, single(exam, v(result(exam, pv), { open: true }), null));
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
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
		expect(document.querySelector('.gl-card')!.classList.contains('gl-card--dim')).toBe(true);
		expect(document.querySelector('.gl-card')!.hasAttribute('aria-disabled')).toBe(false); // its buttons stay usable
		const headEl = document.querySelector('.gl-head')!;
		expect(document.getElementById(headEl.getAttribute('aria-describedby')!)!.textContent).toBe('Does not apply');
		expect(text()).toContain('Guideline, p. 2'); // the full source, behind its one-line summary
		expect(document.querySelector('.cp-pill')!.textContent).toContain('Does not apply');
		expect(document.querySelector('.cp-pill')!.getAttribute('data-category')).toBe('not_applicable');
	});

	it('check_first (no draft): the values, then still open, then the result; eligibility only as the assumptions chip', async () => {
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
		expect(chip.element().querySelector('.cp-sr-only')!.textContent).toContain('Known extra-adrenal cancer; Signs of hormone excess');
		expect(text()).not.toContain('Some eligibility questions');
		const body = document.querySelector('.gl-body')!.textContent!;
		const at = (x: string) => body.indexOf(x);
		expect(at('2.2 cm')).toBeLessThan(at('Growth on prior imaging'));
		expect(at('Growth on prior imaging')).toBeLessThan(at('Benign adenoma'));
		await expect.element(page.getByText('set by the exam').first()).toBeInTheDocument();
		await page.getByRole('button', { name: /^Based on/ }).click(); // the values wait behind "Based on"
		const quote = page.getByText('“2.2 cm left adrenal nodule”');
		await expect.element(quote).not.toBeVisible();
		const row = document.querySelector('.cp-val[tabindex]') as HTMLElement;
		expect(document.getElementById(row.getAttribute('aria-describedby')!)!.textContent!.trim()).toBe('“2.2 cm left adrenal nodule”');
		row.focus();
		await expect.element(quote).toBeVisible();
	});

	it('Task 3 draft card: one value list (assumed, pre-filled, read, still open), then the live result; waiting hidden; no Calculate or Apply', async () => {
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
			assumptions: [assumption('cancer', 'Known cancer')],
			assumed_eligible: true
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByText('⚠ assumes: Known cancer No')).toBeInTheDocument(); // one assumption, named
		const labels = [...document.querySelectorAll('.cp-val .cp-val-label')].map((e) => e.textContent);
		expect(labels).toEqual(['Known cancer', 'Unenhanced HU', 'Size', 'Growth on prior imaging']);
		const badges = [...document.querySelectorAll('.cp-val')].map((e) => [...e.querySelectorAll('.cp-chip')].map((c) => c.textContent).join(','));
		expect(badges).toEqual(['assumed', 'pre-filled', 'read', '']);
		const body = document.querySelector('.gl-body')!.textContent!;
		expect(body.indexOf('Growth on prior imaging')).toBeLessThan(body.indexOf('Benign adenoma'));
		expect(body).not.toContain('Growth rate'); // waiting: hidden
		expect(document.querySelector('.cp-prefill')!.textContent).toBe('8 HU');
		const names = [...document.querySelectorAll('button, [role="button"]')].map((b) => (b.textContent ?? '').trim());
		expect(names.some((n) => /^(apply|calculate)\b/i.test(n))).toBe(false);
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
			assumptions: [assumption('symptoms', 'Stable symptoms', 'Yes')],
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

	it('head: guideline · result pill · assumptions chip, on one line; no value chips', async () => {
		const c = card({ name: 'ESE adrenal incidentaloma', finding: finding.text });
		const pv = preview({
			state: 'check_first',
			proposal: null,
			draft_outcome: outcome({ classification: 'Benign: lipid-rich adenoma', recommendation: 'No further imaging required.', action: 'No further imaging', category: 'none' }),
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm' }),
				draft({ input: 'cancer', label: 'History of extra-adrenal malignancy', role: 'eligibility', state: 'assumed', value: 'No' }),
				draft({ input: 'other', label: 'Imaging for suspected adrenal disease', role: 'eligibility', state: 'assumed', value: 'No' })
			]
		});
		render(CopilotCards, single(c, v(result(c, pv))));
		const titleRow = document.querySelector('.gl-meta')!; // the pills sit on their own row under the name (Task 6)
		await expect.element(page.getByText('No further imaging', { exact: true })).toBeInTheDocument();
		expect(titleRow.textContent).toContain('ESE adrenal incidentaloma');
		expect(titleRow.querySelector('.cp-pill')!.getAttribute('data-category')).toBe('none');
		expect(titleRow.textContent).toContain('⚠ 2 assumed');
		expect(document.querySelector('.cp-vchip')).toBeNull();
		expect((document.querySelector('.gl-card') as HTMLElement).style.getPropertyValue('--gl-accent')).toBe('var(--rv-green-line)');
	});

	it('ESE benign: the result once (no repeat of the action), "5 notes" and ONE source line, each expandable by keyboard', async () => {
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
		// "No further imaging" is said once on screen: in the pill
		expect(document.body.textContent!.split('No further imaging').length - 1).toBe(1);
		const more = page.getByRole('button', { name: 'more' });
		await expect.element(more).toHaveAttribute('aria-expanded', 'false');
		const cls = document.getElementById(more.element().getAttribute('aria-controls')!)!;
		expect(cls.classList.contains('cp-clamp')).toBe(true);
		await more.click();
		await expect.element(page.getByRole('button', { name: 'less' })).toHaveAttribute('aria-expanded', 'true');
		expect(cls.classList.contains('cp-clamp')).toBe(false);
		const notes = page.getByRole('button', { name: /5 notes/ });
		const noteList = document.getElementById(notes.element().getAttribute('aria-controls')!)!;
		expect(noteList.hidden).toBe(true);
		(notes.element() as HTMLElement).focus();
		await userEvent.keyboard('{Enter}');
		expect(noteList.hidden).toBe(false);
		const first = page.getByRole('button', { name: /Note one/ });
		await first.click();
		await expect.element(first).toHaveAttribute('aria-expanded', 'true');
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
			deciding_input: { input: 'brock', label: 'Brock risk' },
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

	it('every input is editable in the value list: an open question is answered, an assumed value changed; no Calculate, no Apply', async () => {
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
		const p = { ...single(c, v(result(c, pv), { open: true })), onEdit: vi.fn() };
		render(CopilotCards, p);
		await page.getByRole('button', { name: /^Based on/ }).click();
		await page.getByRole('button', { name: 'Answer Brock risk' }).click();
		await page.getByRole('combobox', { name: 'Answer for Brock risk' }).selectOptions('Under 10%');
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'brock', 'Under 10%');
		await page.getByRole('button', { name: 'Change Known cancer' }).first().click(); // Check holds the assumed value; the list repeats it
		await page.getByRole('combobox', { name: 'Answer for Known cancer' }).selectOptions('Yes');
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'cancer', 'Yes');
		const names = [...document.querySelectorAll('button, [role="button"]')].map((b) => (b.textContent ?? '').trim());
		expect(names.some((n) => /^(apply|calculate)\b/i.test(n))).toBe(false);
	});

	it('the result is live: while the card re-previews it says so; a failed edit shows its note', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, draft_outcome: outcome(), draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm' })] });
		const r = render(CopilotCards, { ...single(c, v(result(c, pv), { open: true, loading: true })), onEdit: vi.fn() });
		const verdict = page.getByRole('region', { name: 'Verdict' });
		await expect.element(verdict).toHaveAttribute('aria-busy', 'true');
		expect(document.querySelector('.cp-pill')!.getAttribute('aria-busy')).toBe('true'); // the pill is about to change
		expect(document.querySelector('.cp-pill')!.classList.contains('cp-pill--busy')).toBe(true);
		await expect.element(page.getByText('Updating on the new values…')).toBeInTheDocument();
		await r.rerender({ views: { [cardRef(c)]: v(result(c, pv), { open: true, editError: "Couldn't apply that change; it was undone" }) } });
		await expect.element(page.getByRole('alert')).toHaveTextContent('it was undone');
		await expect.element(page.getByText('On these values')).toBeInTheDocument();
	});

	it('the action is in the pill; the recommendation shows in full when it says more (here its later steps)', async () => {
		const c = card({ key: 'bosniak-renal-cyst', name: 'Bosniak 2019', finding: finding.text });
		const pv = preview({
			proposal: null,
			draft_outcome: outcome({
				classification: 'Bosniak IIF: minimally thickened smooth wall',
				recommendation: 'Follow-up CT or MRI at 6 months and 12 months, then yearly for 5 years.',
				headline: 'Bosniak IIF',
				action: 'CT or MRI at 6 months',
				category: 'surveillance'
			})
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toHaveTextContent('Bosniak IIF');
		expect(document.querySelector('.cp-pill')!.textContent).toContain('CT or MRI at 6 months');
		expect(document.querySelector('.cp-recommendation')!.textContent).toBe('Follow-up CT or MRI at 6 months and 12 months, then yearly for 5 years.');
	});

	it('when the recommendation starts with the action, only the rest shows', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, draft_outcome: outcome({ classification: 'Solid 6–8 mm', recommendation: 'CT at 6–12 months, then consider CT at 18–24 months.', action: 'CT at 6–12 months', category: 'surveillance' }) });
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toBeInTheDocument();
		expect(document.querySelector('.cp-recommendation')!.textContent).toBe('then consider CT at 18–24 months.');
	});

	it('an outcome whose category is not_applicable (e.g. manage as solid) is a full verdict: not dimmed, no "Does not apply"', async () => {
		const c = card({ key: 'bosniak-renal-cyst', name: 'Bosniak 2019', finding: finding.text });
		const pv = preview({
			proposal: null,
			draft_outcome: outcome({ classification: 'Not a cystic mass: Bosniak does not classify it', recommendation: 'Manage as a solid renal mass.', headline: 'Not cystic', action: 'Manage as solid renal mass', category: 'not_applicable' })
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toHaveTextContent('Not cystic');
		expect(document.querySelector('.cp-pill')!.textContent).toContain('Manage as solid renal mass');
		expect(document.querySelector('.gl-card')!.classList.contains('gl-card--dim')).toBe(false);
		expect(document.body.textContent).not.toContain('Does not apply');
		expect(document.querySelector('.cp-pill')!.classList.contains('cp-pill--excluded')).toBe(false);
		expect(document.querySelector('[data-testid="cp-exclusion"]')).toBeNull();
	});

	it('checkpoint 4: N/A rows hidden behind "+N not applicable"', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({
			proposal: null,
			draft_outcome: outcome({ classification: 'Benign: x', recommendation: 'No further imaging required.', action: 'No further imaging', category: 'none' }),
			draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm' }), draft({ input: 'side', label: 'Solid component', state: 'not_applicable' })]
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		await page.getByRole('button', { name: /^Based on/ }).click();
		await expect.element(page.getByText('2.2 cm', { exact: true })).toBeInTheDocument();
		expect(document.querySelector('.cp-recommendation')).toBeNull(); // the pill already says it
		expect(document.body.textContent).not.toContain('Solid component');
		await page.getByRole('button', { name: '+1 not applicable' }).click();
		await expect.element(page.getByText('Solid component')).toBeInTheDocument();
	});

	it('checkpoint 4: a card that does not apply leads with the specific reason; the generic text and the values wait behind toggles', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({
			state: 'does_not_apply',
			proposal: null,
			exclusion: outcome({ classification: 'Not for patients under 35, with known cancer, or immunosuppressed.', recommendation: '' }),
			exclusion_reason: { input: 'age', label: 'Age', value: '28' },
			draft: [draft({ input: 'age', label: 'Age', state: 'read', value: '28' })]
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		const verdict = page.getByRole('region', { name: 'Verdict' }).element();
		await expect.element(page.getByText('Age 28').first()).toBeInTheDocument();
		expect(verdict.querySelector('.cp-headline')!.textContent).toBe('Age 28');
		const cls = verdict.querySelector('.cp-classification') as HTMLElement;
		expect(cls.hidden).toBe(true);
		await page.getByRole('button', { name: 'full reason' }).click();
		expect(cls.hidden).toBe(false);
		const valuesToggle = page.getByRole('button', { name: /^values/ });
		const list = document.getElementById(valuesToggle.element().getAttribute('aria-controls')!)!;
		expect(list.hidden).toBe(true);
		await valuesToggle.click();
		expect(list.hidden).toBe(false);
	});

	it('a single assumption is named in full in the head (the chip truncates only on overflow)', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({ proposal: null, draft_outcome: outcome({ category: 'none' }), draft: [draft({ input: 'x', label: 'History of extra-adrenal malignancy', role: 'eligibility', state: 'assumed', value: 'No' })] });
		render(CopilotCards, single(c, v(result(c, pv))));
		const one = page.getByText('⚠ assumes: History of extra-adrenal malignancy No');
		await expect.element(one).toBeInTheDocument();
		expect(getComputedStyle(one.element()).textOverflow).toBe('ellipsis');
	});

	it('several outcomes remain (no most_likely): "Depends on <deciding_input.label>" still shows its branches', async () => {
		const c = card({ finding: finding.text });
		const pv = preview({
			proposal: null,
			most_likely: null,
			deciding_input: { input: 'brock', label: 'Brock risk' },
			deciding: [{ answer: 'Under 10%', headline: 'CT surveillance', category: 'surveillance' }, { answer: '10% or more', headline: 'PET-CT', category: 'workup' }],
			possible: ['CT surveillance', 'PET-CT'],
			draft: [draft({ input: 'brock', label: 'Brock risk', state: 'asked', needed: true })]
		});
		render(CopilotCards, single(c, v(result(c, pv), { open: true })));
		const region = page.getByRole('region', { name: 'What decides it' });
		await expect.element(region).toHaveTextContent('Depends on Brock risk');
		expect(region.element().querySelectorAll('.cp-branches li')).toHaveLength(2);
		expect(region.element().textContent).not.toContain('Most likely');
	});

	it('scope_doubt: "⚠ check applicability" in the head; a warning first in the body; the row highlighted; Confirm or Change', async () => {
		const c = card({ key: 'nhs-aaa-surveillance', name: 'NHS AAA surveillance', finding: finding.text });
		const pv = preview({
			state: 'check_first',
			proposal: null,
			draft_outcome: outcome({ classification: 'Medium AAA', recommendation: 'Scan every 3 months.', action: 'Scan every 3 months', category: 'surveillance' }),
			scope_doubt: ['diameter_mm'],
			draft: [
				draft({ input: 'sex', label: 'Sex', state: 'read', value: 'Male' }),
				draft({ input: 'diameter_mm', label: 'Maximum diameter', state: 'prefilled', value: '35 mm', why: ['x'], options: [] })
			]
		});
		const p = { ...single(c, v(result(c, pv), { open: true })), onEdit: vi.fn() };
		render(CopilotCards, p);
		await expect.element(page.getByTestId('cp-scope-doubt-chip')).toHaveTextContent('⚠ check applicability');
		expect(document.querySelector('.gl-title-row')!.textContent).not.toContain('check first'); // said once
		const note = page.getByTestId('cp-scope-doubt');
		await expect.element(note).toHaveTextContent('Maximum diameter: 35 mm');
		await expect.element(note).toHaveTextContent('pre-filled · would make NHS AAA surveillance not apply');
		// first in the body: the Check zone holds it
		const first = document.querySelector('.gl-body .cp-pack-body')!.firstElementChild!;
		expect(first.getAttribute('data-testid')).toBe('cp-check');
		expect(first.contains(note.element())).toBe(true);
		await page.getByRole('button', { name: /^Based on/ }).click();
		const row = [...document.querySelectorAll('.cp-val')].find((e) => e.textContent!.includes('Maximum diameter'))!;
		expect(row.classList.contains('cp-val--doubt')).toBe(true);
		await page.getByRole('button', { name: 'Confirm Maximum diameter 35 mm' }).click();
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'diameter_mm', '35 mm');
		await page.getByRole('button', { name: 'Change Maximum diameter' }).first().click();
		await page.getByRole('textbox', { name: 'Answer for Maximum diameter' }).fill('55 mm');
		await page.getByRole('button', { name: 'Save' }).click();
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'diameter_mm', '55 mm');
	});

	it('scope_doubt on an option id: the warning shows words, Confirm sends the stored id', async () => {
		const c = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015', finding: finding.text });
		const pv = preview({
			state: 'check_first',
			proposal: null,
			draft_outcome: outcome({ headline: 'X', action: 'Y', category: 'workup' }),
			scope_doubt: ['growth'],
			draft: [draft({ input: 'growth', label: 'Growth', state: 'prefilled', value: 'diameter_clear_growth', why: ['x'], options: ['diameter_stable', 'diameter_clear_growth'] })]
		});
		const p = { ...single(c, v(result(c, pv), { open: true })), onEdit: vi.fn() };
		render(CopilotCards, p);
		const note = page.getByTestId('cp-scope-doubt');
		await expect.element(note).toHaveTextContent('Growth: Diameter clear growth');
		await expect.element(note).toHaveTextContent('pre-filled');
		expect(note.element().textContent).not.toContain('diameter_clear_growth');
		await page.getByRole('button', { name: 'Confirm Growth Diameter clear growth' }).click();
		expect(p.onEdit).toHaveBeenCalledWith(cardRef(c), 'growth', 'diameter_clear_growth');
	});

	it('a COLLAPSED sibling card shows each column\'s "⚠ check applicability" and assumption chips', async () => {
		const c = card({ finding: finding.text, siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
		const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
		const doubtful = preview({
			state: 'check_first',
			proposal: null,
			draft_outcome: outcome({ action: 'CT at 3 months', category: 'surveillance' }),
			scope_doubt: ['age'],
			draft: [draft({ input: 'age', label: 'Age', state: 'prefilled', value: '30' })]
		});
		const assumedOne = preview({
			proposal: null,
			draft_outcome: outcome({ category: 'surveillance' }),
			assumptions: [assumption('cancer', 'Known cancer', 'No', { decisive: true })],
			draft: [draft({ input: 'cancer', label: 'Known cancer', state: 'assumed', value: 'No' })]
		});
		render(
			CopilotCards,
			single(c, v(null, { open: false, columns: { [c.key]: { loading: false, error: null, result: result(c, assumedOne) }, [bts.key]: { loading: false, error: null, result: result(bts, doubtful) } } }))
		);
		const meta = document.querySelector('.cp-sib-pills')!;
		await expect.element(page.getByText('⚠ check applicability')).toBeInTheDocument();
		expect(meta.textContent).toContain('⚠ check applicability');
		expect(meta.textContent).toContain('⚠ assumes: Known cancer No');
		expect(document.querySelector('.gl-body')).toBeNull(); // still collapsed
	});

	it('PackCard takes an assumptions list directly (B1 feeds Task 3)', async () => {
		const { default: PackCard } = await import('./PackCard.svelte');
		const c = card({ finding: finding.text });
		render(PackCard, { card: c, view: v(result(c, preview()), { open: true }), assumptions: ['Not pregnant'], onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn() });
		await expect.element(page.getByText('⚠ assumes: Not pregnant')).toBeInTheDocument();
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
