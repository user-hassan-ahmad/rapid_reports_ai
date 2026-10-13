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
});
