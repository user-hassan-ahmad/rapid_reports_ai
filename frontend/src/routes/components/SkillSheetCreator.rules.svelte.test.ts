// The creator's Rules step fallback: a failed decision run never blocks creation; the writer runs and the notice shows.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import SkillSheetCreator from './SkillSheetCreator.svelte';

type Call = { url: string; body: any };

afterEach(() => vi.unstubAllGlobals());

describe('SkillSheetCreator rules step', () => {
	it('builds the template when the decision run fails, and shows the notice', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
			calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : null });
			if (url.endsWith('/skill-sheet/decide')) return new Response('x', { status: 500 });
			if (url.endsWith('/skill-sheet/analyze'))
				return new Response(JSON.stringify({ success: true, skill_sheet: '# Skill Sheet: T', summary: {}, decisions: [], notice: '' }));
			return new Response(JSON.stringify({ success: true, tags: [], templates: [] }));
		}));
		render(SkillSheetCreator, {});
		await userEvent.fill(page.getByPlaceholder('e.g. CT chest with IV contrast', { exact: false }), 'CT abdomen');
		for (const n of [1, 2, 3]) {
			await page.getByRole('button', { name: `Report ${n}` }).click();
			await userEvent.fill(page.getByPlaceholder('Paste complete report...'), `Report ${n} findings. Liver normal.`);
		}
		await page.getByRole('button', { name: 'Analyse my style' }).click();
		await expect
			.element(page.getByText("We couldn't pre-check your rules; review them on the Style step."))
			.toBeInTheDocument();
		const decide = calls.find((c) => c.url.endsWith('/decide'))!;
		expect(decide.body).toMatchObject({ scan_type: 'CT abdomen', protocol_notes: '', template_name: '' });
		const analyze = calls.find((c) => c.url.endsWith('/analyze'))!;
		expect(analyze.body.changes).toEqual([]);
	});

	it('shows the Style checks under the summary and applies a tap through the ledger', async () => {
		const calls: Call[] = [];
		const fixed = { id: 'fixed:x', kind: 'fixed', step: 'style', title: 'Breath-holding was adequate.', evidence: [], ledger_kind: 'fixed',
			key: 'Breath-holding was adequate.', selected: null, rank: 3,
			choices: [{ id: 'always', label: 'Always the same', choice: { keep: 'always' } }, { id: 'dictated', label: 'Only when dictated', choice: { keep: 'dictated' } }] };
		vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
			const body = init?.body ? JSON.parse(init.body as string) : null;
			calls.push({ url, body });
			if (url.endsWith('/skill-sheet/decide')) return new Response('x', { status: 500 });
			if (url.endsWith('/skill-sheet/analyze'))
				return new Response(JSON.stringify({ success: true, skill_sheet: 'SHEET', summary: {}, decisions: [], notice: '' }));
			if (url.endsWith('/skill-sheet/sheet-checks'))
				return new Response(JSON.stringify({ success: true, fixed_cards: body.skill_sheet === 'SHEET' ? [fixed] : [], errors: [] }));
			if (url.endsWith('/skill-sheet/apply-decisions'))
				return new Response(JSON.stringify({ success: true, skill_sheet: 'SHEET2', decisions: [{ kind: 'fixed', key: fixed.key, choice: { keep: 'dictated' }, by: 'radiologist', at: 't', source: 'creation' }], applied: [], unmatched: [], stale_quotes: [] }));
			return new Response(JSON.stringify({ success: true, tags: [], templates: [] }));
		}));
		render(SkillSheetCreator, {});
		await userEvent.fill(page.getByPlaceholder('e.g. CT chest with IV contrast', { exact: false }), 'MR liver');
		for (const n of [1, 2, 3]) {
			await page.getByRole('button', { name: `Report ${n}` }).click();
			await userEvent.fill(page.getByPlaceholder('Paste complete report...'), `Report ${n}. Breath-holding was adequate.`);
		}
		await page.getByRole('button', { name: 'Analyse my style' }).click();
		await page.getByRole('button', { name: 'Breath-holding was adequate.: Only when dictated' }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith('/apply-decisions'))).toBe(true));
		expect(calls.find((c) => c.url.endsWith('/apply-decisions'))!.body).toMatchObject({
			skill_sheet: 'SHEET', source: 'creation', changes: [{ kind: 'fixed', key: 'Breath-holding was adequate.', choice: { keep: 'dictated' }, source: 'creation' }] });
		await expect.element(page.getByText('Always printed')).not.toBeInTheDocument();   // re-run on the applied sheet
	});

	it('stays on the Rules step and shows the error when the build is refused', async () => {
		vi.stubGlobal('fetch', vi.fn(async (url: string) => {
			if (url.endsWith('/skill-sheet/decide')) return new Response('x', { status: 500 });
			if (url.endsWith('/skill-sheet/analyze')) return new Response(JSON.stringify({ success: false, error: 'An example report is too long' }));
			return new Response(JSON.stringify({ success: true, tags: [], templates: [] }));
		}));
		render(SkillSheetCreator, {});
		await userEvent.fill(page.getByPlaceholder('e.g. CT chest with IV contrast', { exact: false }), 'CT abdomen');
		for (const n of [1, 2, 3]) {
			await page.getByRole('button', { name: `Report ${n}` }).click();
			await userEvent.fill(page.getByPlaceholder('Paste complete report...'), `Report ${n}.`);
		}
		await page.getByRole('button', { name: 'Analyse my style' }).click();
		await expect.element(page.getByText('An example report is too long').first()).toBeInTheDocument();
		await expect.element(page.getByText('Check your rules')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
	});
});
