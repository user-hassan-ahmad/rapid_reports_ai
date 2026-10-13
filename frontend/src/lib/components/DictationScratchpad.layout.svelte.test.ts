// The Copilot rail's layout must not touch anyone with the Copilot off (final review minor 10). SYNTHETIC props.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';

vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
const { default: DictationScratchpad } = await import('./DictationScratchpad.svelte');

const root = () => document.querySelector('[data-testid="scratchpad-root"]') as HTMLElement;
// layout classes only (Svelte adds its own scoping class)
const classes = (el: Element) => [...el.classList].filter((c) => !c.startsWith('svelte-')).sort();

describe('DictationScratchpad layout with the Copilot', () => {
	it('Copilot off: no row box (display: contents), the column keeps its original classes, no rail', async () => {
		render(DictationScratchpad, {});
		await expect.poll(() => !!root()).toBe(true);
		expect(classes(root())).toEqual([]);
		expect(getComputedStyle(root()).display).toBe('contents');
		const column = root().firstElementChild as HTMLElement;
		expect(classes(column)).toEqual(['flex', 'flex-1', 'flex-col', 'min-h-0'].sort());
		expect(document.querySelector('[data-testid="copilot-rail"]')).toBeNull();
	});

	it("flag on but the stack view not showing (no regions): still today's layout", async () => {
		render(DictationScratchpad, { stackCopilot: true, hybridStack: true, stackRegions: [] });
		await expect.poll(() => !!root()).toBe(true);
		expect(classes(root())).toEqual([]);
		expect(document.querySelector('[data-testid="copilot-rail"]')).toBeNull();
	});

	it('Copilot active: the row layout and the rail beside the scratchpad', async () => {
		render(DictationScratchpad, { stackCopilot: true, hybridStack: true, stackRegions: [{ name: 'Lungs', includes: '' }], stackGroups: ['Lungs'] });
		await expect.poll(() => root()?.className).toContain('flex-row');
		await expect.element(page.getByTestId('copilot-rail')).toBeInTheDocument();
		expect((root().firstElementChild as HTMLElement).classList.contains('min-w-0')).toBe(true);
	});
});
