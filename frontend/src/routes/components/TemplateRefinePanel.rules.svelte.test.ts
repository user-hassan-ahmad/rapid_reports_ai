// The refine panel's rules review: Required values (and the first-use decision run) applied through the ledger;
// the cards a save or a chat edit returns (a confirmed item kept) and stored unmatched entries come back as cards.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import TemplateRefinePanel from './TemplateRefinePanel.svelte';

const card = {
	id: 'value:lvef', kind: 'value', step: 'review', title: 'LVEF', evidence: [], ledger_kind: 'value', key: 'LVEF',
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'relevant', label: 'Only when relevant', choice: { need: 'relevant' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected: 'every', rank: 1
};
const template = { id: 't1', name: 'Cardiac', tags: [], template_config: { generation_mode: 'skill_sheet_guided', skill_sheet: 'SHEET', scan_type: 'MR' } };
const KEPT = 'This would remove something you confirmed, so it was kept; use the card below to change it.';

type Call = { url: string; body: any; method: string };

let checksBody: Record<string, unknown> = { success: true, fixed_cards: [], duplicate_cards: [], normal_report: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [] };

afterEach(() => vi.unstubAllGlobals());

function routes(calls: Call[], over: { decideCards?: unknown[]; refine?: unknown; put?: unknown } = {}) {
	return vi.fn(async (url: string, init: RequestInit) => {
		const body = init?.body ? JSON.parse(init.body as string) : null;
		calls.push({ url, body, method: init?.method ?? 'GET' });
		if (url.endsWith('/skill-sheet/decide'))
			return new Response(JSON.stringify({ success: true, ran: false, cards: over.decideCards ?? [card], more: [], kept: [], defaults: [], notice: '', run: {} }));
		if (url.endsWith('/skill-sheet/sheet-checks')) return new Response(JSON.stringify(checksBody));
		if (url.endsWith('/skill-sheet/apply-decisions'))
			return new Response(JSON.stringify({ success: true, skill_sheet: 'SHEET2', decisions: [{ kind: 'value', key: 'LVEF', choice: { need: 'not_needed' }, by: 'radiologist', at: 't', source: 'first_use_review' }], applied: [], unmatched: [], stale_quotes: [] }));
		if (url.endsWith('/skill-sheet/refine') && over.refine) return new Response(JSON.stringify(over.refine));
		if (url.endsWith('/api/templates/t1'))
			return new Response(JSON.stringify(over.put ?? { success: true, template: { ...template, template_config: { ...template.template_config, skill_sheet: 'SHEET2' } } }));
		return new Response(JSON.stringify({ success: true, templates: [] }));
	});
}

describe('TemplateRefinePanel rules review', () => {
	it('shows Required values, applies a change through the ledger and saves the ledger', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await expect.element(page.getByText("Your template's rules")).toBeInTheDocument();
		await page.getByText("Your template's rules").click();
		await page.getByRole('button', { name: 'LVEF: Not needed' }).click();
		await page.getByRole('button', { name: 'Apply' }).click();
		await expect.element(page.getByText('Rules updated. Save to apply them to future reports.')).toBeInTheDocument();
		const apply = calls.find((c) => c.url.endsWith('/apply-decisions'))!;
		expect(apply.body).toMatchObject({ skill_sheet: 'SHEET', source: 'first_use_review',
			changes: [{ kind: 'value', key: 'LVEF', choice: { need: 'not_needed' }, source: 'first_use_review' }] });
		await page.getByRole('button', { name: 'Save' }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
		const put = calls.find((c) => c.method === 'PUT')!;
		expect(put.body.template_config.skill_sheet).toBe('SHEET2');
		expect(put.body.template_config.decisions[0]).toMatchObject({ key: 'LVEF', choice: { need: 'not_needed' } });
		const decide = calls.find((c) => c.url.endsWith('/decide'))!;
		expect(decide.body).toMatchObject({ template_id: 't1', examples: [], scan_type: 'MR' });
	});

	it('works without the review when the decide call fails', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
		render(TemplateRefinePanel, { template });
		await expect.element(page.getByText('Tell me what to change', { exact: false })).toBeInTheDocument();
		await expect.element(page.getByText("Your template's rules")).not.toBeInTheDocument();
	});

	it('shows the card a chat edit returns when it kept a confirmed item', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls, {
			decideCards: [],
			refine: { success: true, skill_sheet: 'SHEET', response: `Done. ${KEPT}`, applied: true, cards: [{ ...card, step: 'chat', selected: null }], decisions: [] }
		}));
		render(TemplateRefinePanel, { template });
		await userEvent.fill(page.getByPlaceholder('e.g. Always mention', { exact: false }), 'remove the values');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.element(page.getByText(KEPT, { exact: false })).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'LVEF: Not needed' })).toBeInTheDocument();
		const refine = calls.find((c) => c.url.endsWith('/refine'))!;
		expect(refine.body.decisions).toEqual([]);
	});

	it('shows the card the save returns when it kept a confirmed item', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls, {
			decideCards: [],
			refine: { success: true, skill_sheet: 'SHEET3', response: 'Done.', applied: true },
			put: { success: true, notice: KEPT, cards: [{ ...card, step: 'chat', selected: null }], template: { ...template } }
		}));
		render(TemplateRefinePanel, { template });
		await userEvent.fill(page.getByPlaceholder('e.g. Always mention', { exact: false }), 'tidy it');
		await page.getByRole('button', { name: 'Send' }).click();
		await page.getByRole('button', { name: 'Save' }).click();
		await expect.element(page.getByText(KEPT)).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'LVEF: Not needed' })).toBeInTheDocument();
	});

	it('says No changes when Apply changes nothing', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await page.getByText("Your template's rules").click();
		await page.getByRole('button', { name: 'Apply' }).click();
		await expect.element(page.getByRole('status').filter({ hasText: 'No changes' })).toBeInTheDocument();
		await expect.element(page.getByText('Rules updated', { exact: false })).not.toBeInTheDocument();
		expect(calls.some((c) => c.url.endsWith('/apply-decisions'))).toBe(false);
	});

	it('blocks Apply while a refine turn is in flight, and Send and Save while an Apply runs', async () => {
		const calls: Call[] = [];
		let finishRefine: (r: Response) => void = () => {};
		const base = routes(calls);
		vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => {
			if (url.endsWith('/skill-sheet/refine')) return new Promise<Response>((res) => (finishRefine = res));
			return base(url, init);
		}));
		render(TemplateRefinePanel, { template });
		await page.getByText("Your template's rules").click();
		await userEvent.fill(page.getByPlaceholder('e.g. Always mention', { exact: false }), 'tidy it');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.element(page.getByRole('button', { name: 'Apply' })).toBeDisabled();
		await expect.element(page.getByRole('button', { name: 'LVEF: Not needed' })).toBeDisabled();
		finishRefine(new Response(JSON.stringify({ success: true, skill_sheet: 'SHEET', response: 'Done.', applied: true })));
		await expect.element(page.getByRole('button', { name: 'Apply' })).not.toBeDisabled();
		// now an Apply that has not returned yet: no chat send, no save
		let finishApply: () => void = () => {};
		const held = new Promise<void>((res) => (finishApply = res));
		vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
			if (url.endsWith('/apply-decisions')) await held;
			return base(url, init);
		}));
		await page.getByRole('button', { name: 'LVEF: Not needed' }).click();
		await page.getByRole('button', { name: 'Apply' }).click();
		await userEvent.fill(page.getByPlaceholder('e.g. Always mention', { exact: false }), 'more');
		await expect.element(page.getByRole('button', { name: 'Send' })).toBeDisabled();
		await expect.element(page.getByRole('button', { name: 'Save' })).toBeDisabled();
		finishApply();
		await expect.element(page.getByText('Rules updated. Save to apply them to future reports.')).toBeInTheDocument();
	});
});

describe('TemplateRefinePanel style checks', () => {
	it('shows how the report will read and applies a tap through the ledger, keeping the rules review', async () => {
		checksBody = { success: true, fixed_cards: [], duplicate_cards: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [],
			normal_report: [{ section: 'FINDINGS', header: 'Findings:', sentences: [{ key: 'Heart :: pericardium', text: 'The pericardium is normal.', kind: 'normal', paragraph: 'Heart' }] }] };
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await page.getByText('How your report will read').click();
		await page.getByRole('button', { name: 'Edit: The pericardium is normal.' }).click();
		await page.getByRole('button', { name: 'Remove', exact: true }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith('/apply-decisions'))).toBe(true));
		const apply = calls.find((c) => c.url.endsWith('/apply-decisions'))!;
		expect(apply.body.changes).toEqual([{ kind: 'normal', key: 'Heart :: pericardium', choice: { text: '' }, source: 'first_use_review' }]);
		// the checks are re-run on the applied sheet; the rules review is still there to answer
		await vi.waitFor(() => expect(calls.filter((c) => c.url.endsWith('/sheet-checks')).at(-1)?.body.skill_sheet).toBe('SHEET2'), { timeout: 3000 });
		await expect.element(page.getByText("Your template's rules")).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Save' })).toBeInTheDocument();
	});

	it('does not re-run the checks when a turn leaves the sheet and the ledger unchanged', async () => {
		checksBody = { success: true, fixed_cards: [], duplicate_cards: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [],
			normal_report: [{ section: 'FINDINGS', header: 'Findings:', sentences: [{ key: 'Heart :: pericardium', text: 'The pericardium is normal.', kind: 'normal', paragraph: 'Heart' }] }] };
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls, { refine: { success: true, skill_sheet: 'SHEET', response: 'No change was needed.', applied: true, decisions: [] } }));
		render(TemplateRefinePanel, { template });
		await expect.element(page.getByText('How your report will read')).toBeInTheDocument();
		await userEvent.fill(page.getByPlaceholder('e.g. Always mention', { exact: false }), 'nothing');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.element(page.getByText('No change was needed.')).toBeInTheDocument();
		await new Promise((r) => setTimeout(r, 800));
		expect(calls.filter((c) => c.url.endsWith('/sheet-checks'))).toHaveLength(1);
	});

	it('shows no checks when they fail', async () => {
		checksBody = { success: false };
		vi.stubGlobal('fetch', routes([]));
		render(TemplateRefinePanel, { template });
		await expect.element(page.getByText("Your template's rules")).toBeInTheDocument();
		await expect.element(page.getByText('How your report will read')).not.toBeInTheDocument();
	});
});
