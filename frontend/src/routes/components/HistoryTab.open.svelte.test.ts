// History reopens a saved report into the full viewer and rail (Plan 3 E2, spec §12.6). SYNTHETIC reports and items
// only; the review API and the workspace endpoints are mocked, every other fetch answers "not found". Opening loads
// the stored run (getReview) and never re-runs anything (no rerun, no probe).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { ReviewItem, ReviewResponse } from '$lib/review/types';

const getReview = vi.fn();
const rerun = vi.fn(async () => ({ success: true, status: 'running' }));
const probe = vi.fn();
const reprepare = vi.fn();
vi.mock('$lib/review/api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: vi.fn(),
	rerun: (...a: unknown[]) => rerun(...(a as [])),
	probe: (...a: unknown[]) => probe(...a),
	reprepare: (...a: unknown[]) => reprepare(...a)
}));
vi.mock('$lib/review/workspace', () => ({
	loadWorkspace: vi.fn(async () => ({ tab: 'review', expanded_ids: [], density: 'full', last_text_hash: null })),
	saveWorkspace: vi.fn(async (_r: string, s: unknown) => s),
	createWorkspaceSaver: () => ({ schedule: vi.fn(), flush: vi.fn(async () => {}), cancel: vi.fn() })
}));

const { default: HistoryTab } = await import('./HistoryTab.svelte');
const { default: IntelliDictateTab } = await import('./IntelliDictateTab.svelte');
const { default: TemplatedReportTab } = await import('./TemplatedReportTab.svelte');
const { reportsStore } = await import('$lib/stores/reports');
const { templatesStore, selectedTemplateId } = await import('$lib/stores/templates');

const REPORT = `FINDINGS:
The spleen measures 9 cm. No ascites.

IMPRESSION:
Normal study.`;

const QUICK = {
	id: 'rep-quick',
	report_type: 'auto',
	template_id: null,
	model_used: 'synthetic-model',
	report_content: REPORT,
	description: 'Synthetic quick report',
	created_at: '2026-10-05T10:00:00Z',
	input_data: { variables: { SCAN_TYPE: 'CT abdomen', CLINICAL_HISTORY: 'Pain.', FINDINGS: 'spleen 9 cm' } }
};

const TEMPLATE = {
	id: 'tpl-1',
	name: 'Synthetic template',
	variables: ['FINDINGS', 'CLINICAL_HISTORY'],
	template_config: null,
	tags: []
};

const TEMPLATED = {
	...QUICK,
	id: 'rep-tpl',
	report_type: 'templated',
	template_id: 'tpl-1',
	description: 'Synthetic templated report',
	input_data: { variables: { FINDINGS: 'spleen 9 cm', CLINICAL_HISTORY: 'Pain.' } }
};

function item(reportId: string): ReviewItem {
	const start = REPORT.indexOf('9 cm');
	return {
		id: 'a1',
		key: 'a1',
		report_id: reportId,
		run_id: 'run1',
		lane: 'accuracy',
		detectors: [],
		kind: 'measurement',
		cls: 'action',
		section: 'FINDINGS',
		anchor: { start, end: start + 4, text: '9 cm' },
		label: 'Measurement differs',
		reason: 'The dictation gives 11 cm.',
		edit: { mode: 'replace', find: '9 cm', replace: '11 cm' },
		status: 'open',
		history: [],
		engine_version: 'test'
	};
}

function stored(reportId: string): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
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
		items: [item(reportId)]
	};
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

beforeEach(async () => {
	await page.viewport(1400, 900);
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => new Response(JSON.stringify({ success: false }), { status: 404 }))
	);
	getReview.mockImplementation(async (id: string) => stored(id));
});

afterEach(() => {
	vi.unstubAllGlobals();
	getReview.mockReset();
	rerun.mockClear();
	probe.mockReset();
	reprepare.mockReset();
	selectedTemplateId.set(null);
});

describe('History: Open and Preview', () => {
	it('offers Open (into the viewer) beside Preview (the read-only modal)', async () => {
		reportsStore.addReport(QUICK);
		const openReport = vi.fn();
		const viewReport = vi.fn();
		render(HistoryTab, { events: { openReport, viewReport } } as never);
		await page.getByRole('button', { name: 'Open Synthetic quick report' }).click();
		expect(openReport).toHaveBeenCalledTimes(1);
		expect(openReport.mock.calls[0][0].detail.id).toBe('rep-quick');
		await page.getByRole('button', { name: 'Preview Synthetic quick report' }).click();
		expect(viewReport).toHaveBeenCalledTimes(1);
	});
});

describe('quick tab: openExisting', () => {
	it('renders the viewer and rail from the stored run, without rerun or probe', async () => {
		const { component, container } = render(IntelliDictateTab, {});
		await (component as unknown as { openExisting: (r: typeof QUICK) => Promise<void> }).openExisting(QUICK);
		await pause(400);
		expect(getReview).toHaveBeenCalledWith('rep-quick');
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		await expect.element(page.getByText('Measurement differs').first()).toBeInTheDocument();
		expect(container.querySelector('.cm-content')?.textContent).toContain('The spleen measures 9 cm.');
		expect(rerun).not.toHaveBeenCalled();
		expect(probe).not.toHaveBeenCalled();
		expect(reprepare).not.toHaveBeenCalled();
	});
});

describe('templated tab: openExisting', () => {
	it('selects the template and renders the viewer and rail from the stored run, without rerun or probe', async () => {
		templatesStore.addTemplate(TEMPLATE);
		const { component, container } = render(TemplatedReportTab, {});
		await tick();
		const opened = await (
			component as unknown as { openExisting: (r: typeof TEMPLATED) => Promise<boolean> }
		).openExisting(TEMPLATED);
		expect(opened).toBe(true);
		expect(get(selectedTemplateId)).toBe('tpl-1');
		await pause(400);
		expect(getReview).toHaveBeenCalledWith('rep-tpl');
		await expect.element(page.getByTestId('review-rail')).toBeInTheDocument();
		expect(container.querySelector('.cm-content')?.textContent).toContain('The spleen measures 9 cm.');
		expect(rerun).not.toHaveBeenCalled();
		expect(probe).not.toHaveBeenCalled();
	});

	it('returns false when the report’s template is not available (the page falls back to Preview)', async () => {
		const { component } = render(TemplatedReportTab, {});
		await tick();
		const opened = await (
			component as unknown as { openExisting: (r: typeof TEMPLATED) => Promise<boolean> }
		).openExisting({ ...TEMPLATED, template_id: 'missing' });
		expect(opened).toBe(false);
		expect(getReview).not.toHaveBeenCalled();
	});
});
