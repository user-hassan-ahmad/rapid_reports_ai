import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import type { GuidelineEntry } from '$lib/guidelines/types';
import type { ReviewItem, ReviewResponse } from '../types';

const getReview = vi.fn();
vi.mock('../api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: vi.fn(() => Promise.resolve({ success: true })),
	rerun: vi.fn()
}));

// SYNTHETIC guideline card only.
const CARD: GuidelineEntry = {
	finding_number: 1,
	finding: 'Pancreatic head mass',
	classifications: [
		{ system: 'NCCN', authority: 'NCCN', grade: 'Borderline resectable', criteria: '', management: '' }
	]
};
vi.mock('$lib/guidelines/enhance', () => {
	const data = { findings: [], guidelines: [CARD], urgencySignals: [], applicableGuidelines: [], lookupFailed: false };
	return { peekEnhancement: () => data, loadEnhancement: () => Promise.resolve(data) };
});

const { createReviewStore } = await import('../store');
const { default: RailGuidelines } = await import('./RailGuidelines.svelte');

function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id' | 'kind' | 'cls'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'additions',
		detectors: ['s4.classification'],
		label: over.id,
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

const GRADE = item({
	id: 'g1',
	kind: 'grade',
	cls: 'minor',
	citation: { card: 1 },
	evidence: { finding: 'Pancreatic head mass', system: 'NCCN', grade: 'Borderline resectable' },
	edit: { mode: 'insert', after: 'A 32 mm pancreatic head mass.', replace: 'Borderline resectable.', section: 'FINDINGS' }
});

function response(items: ReviewItem[]): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' } as const;
	return {
		success: true,
		mode: 'live',
		rail: true,
		run: {
			id: 'run1',
			mode: 'live',
			engine_version: 'test',
			pathway: 'quick',
			lanes,
			timings_ms: {},
			cost: {},
			errors: {},
			created_at: null
		},
		lanes,
		items
	} as ReviewResponse;
}

async function mount(items: ReviewItem[]) {
	const store = createReviewStore('rep1');
	getReview.mockResolvedValueOnce(response(items));
	await store.load();
	const onCommand = vi.fn();
	render(RailGuidelines, { reportId: 'rep1', store, onCommand });
	return { store, onCommand };
}

describe('Guidelines tab: Add to report', () => {
	it('runs the rail apply on the matching open additions item, then hides once applied', async () => {
		const { store, onCommand } = await mount([GRADE]);
		const add = page.getByRole('button', { name: 'Add to report', exact: true }).first();
		await expect.element(add).toBeInTheDocument();
		await add.click();
		expect(onCommand).toHaveBeenCalledWith('apply', 'g1');
		await store.setStatus('g1', 'applied', { command: 'apply' });
		await expect.element(page.getByRole('button', { name: 'Add to report', exact: true })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Ask →', exact: true })).toBeInTheDocument();
	});

	it('offers nothing extra without a matching item (Ask stays)', async () => {
		await mount([{ ...GRADE, evidence: { system: 'Other', grade: 'X' }, citation: { card: 9 } }]);
		await expect.element(page.getByRole('button', { name: 'Ask →', exact: true })).toBeInTheDocument();
		expect(page.getByRole('button', { name: 'Add to report', exact: true }).elements()).toHaveLength(0);
	});
});
