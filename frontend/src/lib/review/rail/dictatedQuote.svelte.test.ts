import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ItemCard from './ItemCard.svelte';
import ItemTag from './ItemTag.svelte';
import type { ReviewItem } from '../types';

const item = (evidence: Record<string, unknown> | null): ReviewItem =>
	({
		id: 'i1', key: 'k', report_id: 'r', run_id: 'u', lane: 'accuracy', detectors: [], kind: 'check',
		cls: 'minor', label: 'Check', reason: 'Conflicts.', status: 'open', history: [], engine_version: '',
		anchor: null, edit: null, evidence
	}) as unknown as ReviewItem;

const quote = () => document.querySelector<HTMLElement>('[data-rv-quote]');

describe('dictated quote', () => {
	for (const [name, C] of [['ItemCard', ItemCard], ['ItemTag', ItemTag]] as const) {
		it(`${name} shows the quote as visible text when present`, async () => {
			render(C as never, { item: item({ dictated_quote: 'Small right effusion' }), onCommand: () => {} } as never);
			expect(quote()?.textContent).toContain('You dictated: “Small right effusion”');
			expect(quote()!.getBoundingClientRect().height).toBeGreaterThan(0);
		});
		it(`${name} shows nothing without one`, async () => {
			render(C as never, { item: item({}), onCommand: () => {} } as never);
			expect(quote()).toBeNull();
		});
	}
});
