// The refine panel on the chat-edit router: Undo reverses a turn on the backend, cards apply on tap, and the next
// message after a rejection carries the rejection context.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import TemplateRefinePanel from './TemplateRefinePanel.svelte';

const entry = { kind: 'value', key: 'Width', choice: { need: 'not_needed' }, by: 'radiologist', at: 't', source: 'chat' };
const proposal = { id: 'proposal:1', kind: 'proposal', title: 'Make this change? The Upper paragraph is now called Top.',
	apply: { kind: 'layout', op: { op: 'rename_paragraph', paragraph: 'Upper', to: 'Top' } } };
const template = { id: 't1', name: 'T', tags: [], template_config: { generation_mode: 'skill_sheet_guided',
	skill_sheet: 'SHEET', scan_type: 'MR', decisions: [], rules_step: { reviewed_at: 'x' } } };

afterEach(() => vi.unstubAllGlobals());

type Call = { url: string; body: any; method: string };

function routes(calls: Call[]) {
	return vi.fn(async (url: string, init: RequestInit) => {
		const body = init?.body ? JSON.parse(init.body as string) : null;
		calls.push({ url, body, method: init?.method ?? 'GET' });
		const json = (x: unknown) => new Response(JSON.stringify(x));
		if (url.endsWith('/skill-sheet/refine')) return json({ success: true, skill_sheet: 'SHEET2', applied: true,
			response: "Width is no longer required.\nI wasn't sure about part of that: choose below.",
			behavioral_claim: 'Width is no longer required.', route: 'router', changes: [{ type: 'ledger' }],
			cards: [proposal], decisions: [entry] });
		if (url.endsWith('/refine/undo')) return json({ success: true, skill_sheet: 'SHEET', applied: true,
			response: 'Undone: Width is no longer required.', behavioral_claim: '', route: 'router', changes: [], cards: [], decisions: [] });
		if (url.endsWith('/refine/card')) return json({ success: true, skill_sheet: 'SHEET3', applied: true,
			response: 'The Upper paragraph is now called Top.', behavioral_claim: 'x', route: 'router', changes: [], cards: [],
			decisions: [entry] });
		if (url.endsWith('/skill-sheet/decide')) return json({ success: true, ran: false, cards: [], more: [], kept: [], defaults: [], notice: '', run: {} });
		if (url.endsWith('/api/templates/t1')) return json({ success: true, template: { ...template, template_config: { ...template.template_config, skill_sheet: 'SHEET3' } } });
		return json({ success: true, templates: [] });
	});
}

async function send(text: string) {
	await page.getByPlaceholder('e.g.', { exact: false }).fill(text);
	await page.getByRole('button', { name: 'Send' }).click();
}

describe('TemplateRefinePanel on the chat-edit router', () => {
	it('Undo reverses the turn on the backend, and the next message carries the rejection', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await send('drop width');
		await expect.element(page.getByText('Width is no longer required.', { exact: false })).toBeInTheDocument();
		await page.getByRole('button', { name: 'Undo' }).click();
		await expect.element(page.getByText('Undone: Width is no longer required.')).toBeInTheDocument();
		const undo = calls.find((c) => c.url.endsWith('/refine/undo'))!;
		expect(undo.body).toMatchObject({ skill_sheet: 'SHEET2', changes: [{ type: 'ledger' }], decisions: [entry], template_id: 't1' });
		await send('only the width line');
		const refines = calls.filter((c) => c.url.endsWith('/skill-sheet/refine'));
		expect(refines[1].body.rejection_context).toEqual({ original_instruction: 'drop width', rejected_claim: 'Width is no longer required.' });
		expect(refines[0].body.rejection_context).toBeNull();
	});

	it('a card applies on tap and the saved sheet is the card answer', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await send('drop width and rename the upper part');
		await page.getByRole('button', { name: 'Apply' }).click();
		await expect.element(page.getByText('The Upper paragraph is now called Top.', { exact: true })).toBeInTheDocument();
		const card = calls.find((c) => c.url.endsWith('/refine/card'))!;
		expect(card.body).toMatchObject({ skill_sheet: 'SHEET2', answer: { proposal: proposal.apply }, template_id: 't1' });
		await page.getByRole('button', { name: 'Save' }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
		expect(calls.find((c) => c.method === 'PUT')!.body.template_config.skill_sheet).toBe('SHEET3');
	});
});
