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
const { default: ConfirmDialog } = await import('$lib/components/ConfirmDialog.svelte');
const { createConfirmGate, confirmIfUnsaved } = await import('$lib/utils/confirmGate');
const { EditorView } = await import('@codemirror/view');
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

type Tab = { openExisting: (r: unknown) => Promise<unknown>; hasUnsavedWork: () => boolean };

/** The page's History "Open" guard (routes/+page.svelte handleOpenReport): the gate with its in-app dialog. */
async function openOver(tab: Tab) {
	const gate = createConfirmGate();
	const decision = confirmIfUnsaved(tab, gate.ask);
	const dialog = get(gate.pending)
		? render(ConfirmDialog, {
				open: true,
				title: 'Replace the open report?',
				message: 'x',
				confirmLabel: 'Open anyway',
				onConfirm: () => gate.answer(true),
				onCancel: () => gate.answer(false)
			})
		: null;
	return { decision, dialog };
}

describe('History Open over unsaved work (in-app confirm)', () => {
	it('quick tab: unsaved editor changes ask first; Cancel keeps everything', async () => {
		const { component, container } = render(IntelliDictateTab, {});
		const tab = component as unknown as Tab;
		await tab.openExisting(QUICK);
		await pause(400);
		expect(tab.hasUnsavedWork()).toBe(false);
		// nothing unsaved: Open goes straight through, no dialog
		const clean = await openOver(tab);
		expect(clean.dialog).toBeNull();
		await expect(clean.decision).resolves.toBe(true);

		const viewer = [...container.querySelectorAll('.cm-editor')]
			.map((el) => EditorView.findFromDOM(el as HTMLElement)!)
			.find((v) => v.state.doc.toString().includes('The spleen measures 9 cm.'))!;
		viewer.dispatch({ changes: { from: viewer.state.doc.length, insert: ' Edited.' } });
		await pause(100);
		expect(tab.hasUnsavedWork()).toBe(true);

		const dirty = await openOver(tab);
		expect(dirty.dialog).not.toBeNull();
		await expect.element(page.getByRole('alertdialog', { name: 'Replace the open report?' })).toBeInTheDocument();
		await page.getByRole('button', { name: 'Cancel' }).click();
		await expect(dirty.decision).resolves.toBe(false);
		expect(viewer.state.doc.toString()).toBe(REPORT + ' Edited.');
		dirty.dialog!.unmount();

		const again = await openOver(tab);
		await page.getByRole('button', { name: 'Open anyway' }).click();
		await expect(again.decision).resolves.toBe(true);
	});

	it('templated tab: unsaved editor changes count as unsaved work', async () => {
		if (!get(templatesStore).templates?.some((t: { id: string }) => t.id === TEMPLATE.id))
			templatesStore.addTemplate(TEMPLATE);
		const { component, container } = render(TemplatedReportTab, {});
		await tick();
		const tab = component as unknown as Tab;
		await tab.openExisting(TEMPLATED);
		await pause(400);
		expect(tab.hasUnsavedWork()).toBe(false);
		const viewer = [...container.querySelectorAll('.cm-editor')]
			.map((el) => EditorView.findFromDOM(el as HTMLElement)!)
			.find((v) => v.state.doc.toString().includes('The spleen measures 9 cm.'))!;
		viewer.dispatch({ changes: { from: viewer.state.doc.length, insert: ' Edited.' } });
		await pause(100);
		expect(tab.hasUnsavedWork()).toBe(true);
	});
});

// ── F2 I4 / M5 / M6 ─────────────────────────────────────────────────────────
const { draftStore } = await import('$lib/stores/draft.js');

/** A controllable SSE response for POST /api/quick-report/generate. */
function sseStream() {
	let ctrl!: ReadableStreamDefaultController<Uint8Array>;
	const body = new ReadableStream<Uint8Array>({ start: (c) => (ctrl = c) });
	const enc = new TextEncoder();
	return {
		response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
		send: (event: string, data: unknown) =>
			ctrl.enqueue(enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
		close: () => ctrl.close()
	};
}

const notFound = () => new Response(JSON.stringify({ success: false }), { status: 404 });

function stubFetch(route: (url: string, init?: RequestInit) => Response | Promise<Response> | null) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (u: RequestInfo | URL, init?: RequestInit) => (await route(String(u), init)) ?? notFound())
	);
}

function viewerOf(container: HTMLElement) {
	return [...container.querySelectorAll('.cm-editor')]
		.map((el) => EditorView.findFromDOM(el as HTMLElement)!)
		.find((v) => /FINDINGS:/.test(v.state.doc.toString()));
}

function twoSections(reportId: string, doc: string): ReviewResponse {
	const base = stored(reportId);
	const imp = doc.indexOf('Normal study.');
	return {
		...base,
		items: [
			item(reportId),
			{
				...item(reportId),
				id: 'a2',
				key: 'a2',
				section: 'IMPRESSION',
				label: 'Impression check',
				anchor: { start: imp, end: imp + 13, text: 'Normal study.' },
				edit: { mode: 'replace', find: 'Normal study.', replace: 'Normal.' }
			}
		]
	};
}

const railSections = (container: HTMLElement) =>
	[...container.querySelectorAll('[data-rv-section]')].map((h) => h.getAttribute('data-rv-section'));

const CANDIDATE = {
	model: 'synthetic-model',
	latency_ms: 1,
	run_id: 'x',
	generated_at: '',
	error: null,
	options: []
};

describe('History Open while a report is generating (F2 I4)', () => {
	afterEach(() => {
		draftStore.clearIntelliTab();
		draftStore.clearTemplateTab?.();
	});

	it('quick tab: generating counts as unsaved work; the stream never overwrites the opened report', async () => {
		const streams = [sseStream(), sseStream()];
		let k = 0;
		stubFetch((url) => (url.includes('/api/quick-report/generate') ? streams[k++].response : null));
		draftStore.saveIntelliTab('Pain.', 'CT abdomen', ['Liver'], 'Liver: spleen 9 cm', 'clean');
		const { component, container } = render(IntelliDictateTab, {});
		const tab = component as unknown as Tab & { restoreFromParent: () => Promise<void> };
		await tab.restoreFromParent();
		await pause(300);
		// a first report from these findings: nothing unsaved
		await page.getByRole('button', { name: 'Generate Report' }).click();
		streams[0].send('candidate', { ...CANDIDATE, content: 'FINDINGS:\nFirst report.' });
		streams[0].send('done', { report_id: 'rep-first' });
		streams[0].close();
		await pause(300);
		expect(tab.hasUnsavedWork()).toBe(false);
		// regenerating: the only unsaved work is the report on its way
		await page.getByRole('button', { name: 'Generate Report' }).click();
		await pause(50);
		expect(tab.hasUnsavedWork()).toBe(true);

		await tab.openExisting(QUICK);
		streams[1].send('candidate', { ...CANDIDATE, content: 'FINDINGS:\nGenerated late.' });
		streams[1].send('done', { report_id: 'rep-late' });
		streams[1].close();
		await pause(400);
		expect(viewerOf(container)?.state.doc.toString()).toContain('The spleen measures 9 cm.');
		expect(container.textContent).not.toContain('Generated late.');
		expect(getReview).not.toHaveBeenCalledWith('rep-late');
		expect(tab.hasUnsavedWork()).toBe(false);
	});

	it('templated tab: generating counts as unsaved work; a late answer never overwrites the opened report', async () => {
		if (!get(templatesStore).templates?.some((t: { id: string }) => t.id === TEMPLATE.id))
			templatesStore.addTemplate(TEMPLATE);
		let answer!: (r: Response) => void;
		const late = new Promise<Response>((r) => (answer = r));
		const answers = [
			Promise.resolve(
				new Response(JSON.stringify({ success: true, response: 'FINDINGS:\nFirst report.', model: 'm', report_id: 'rep-first' }))
			),
			late
		];
		let k = 0;
		stubFetch((url) => (url.includes('/api/templates/tpl-1/generate') ? answers[k++] : null));
		draftStore.saveTemplateTab('tpl-1', { CLINICAL_HISTORY: 'Pain.' }, ['Liver'], 'Liver: spleen 9 cm');
		const { component, container } = render(TemplatedReportTab, {});
		await tick();
		const tab = component as unknown as Tab & { restoreFromParent: () => Promise<void> };
		await tab.restoreFromParent();
		await pause(300);
		await page.getByRole('button', { name: 'Generate Report' }).click();
		await pause(300);
		expect(tab.hasUnsavedWork()).toBe(false);
		await page.getByRole('button', { name: 'Generate Report' }).click();
		await pause(50);
		expect(tab.hasUnsavedWork()).toBe(true);

		expect(await tab.openExisting(TEMPLATED)).toBe(true);
		answer(
			new Response(
				JSON.stringify({ success: true, response: 'FINDINGS:\nGenerated late.', model: 'm', report_id: 'rep-late' })
			)
		);
		await pause(400);
		expect(viewerOf(container)?.state.doc.toString()).toContain('The spleen measures 9 cm.');
		expect(container.textContent).not.toContain('Generated late.');
		expect(getReview).not.toHaveBeenCalledWith('rep-late');
		expect(tab.hasUnsavedWork()).toBe(false);
	});
});

describe('Open reads the saved report fresh, and the rail gets its section names (F2 M5 / M6)', () => {
	const FRESH = REPORT.replace('9 cm', '10 cm');

	it('quick tab: openExisting shows GET /api/reports/{id}, not the cached row, with its sections', async () => {
		stubFetch((url, init) =>
			url.endsWith('/api/reports/rep-quick') && (!init?.method || init.method === 'GET')
				? new Response(
						JSON.stringify({
							success: true,
							report: { ...QUICK, report_content: FRESH, candidate_reports: [{ sections: ['IMPRESSION', 'FINDINGS'] }] }
						})
					)
				: null
		);
		getReview.mockImplementation(async (id: string) => twoSections(id, FRESH));
		const { component, container } = render(IntelliDictateTab, {});
		await (component as unknown as Tab).openExisting(QUICK);
		await pause(400);
		expect(viewerOf(container)?.state.doc.toString()).toContain('The spleen measures 10 cm.');
		expect(railSections(container)).toEqual(['IMPRESSION', 'FINDINGS']);
	});

	it('quick tab: a generated candidate passes its sections to the rail', async () => {
		const s = sseStream();
		stubFetch((url) => (url.includes('/api/quick-report/generate') ? s.response : null));
		getReview.mockImplementation(async (id: string) => twoSections(id, REPORT));
		draftStore.saveIntelliTab('Pain.', 'CT abdomen', ['Liver'], 'Liver: spleen 9 cm', 'clean');
		const { component, container } = render(IntelliDictateTab, {});
		await (component as unknown as { restoreFromParent: () => Promise<void> }).restoreFromParent();
		await pause(300);
		await page.getByRole('button', { name: 'Generate Report' }).click();
		s.send('candidate', { ...CANDIDATE, content: REPORT, sections: ['IMPRESSION', 'FINDINGS'] });
		s.send('done', { report_id: 'rep-gen' });
		s.close();
		await pause(500);
		expect(getReview).toHaveBeenCalledWith('rep-gen');
		expect(railSections(container)).toEqual(['IMPRESSION', 'FINDINGS']);
		draftStore.clearIntelliTab();
	});

	it('templated tab: openExisting shows the fresh report and its sections', async () => {
		if (!get(templatesStore).templates?.some((t: { id: string }) => t.id === TEMPLATE.id))
			templatesStore.addTemplate(TEMPLATE);
		stubFetch((url, init) =>
			url.endsWith('/api/reports/rep-tpl') && (!init?.method || init.method === 'GET')
				? new Response(
						JSON.stringify({
							success: true,
							report: { ...TEMPLATED, report_content: FRESH, candidate_reports: [{ sections: ['IMPRESSION', 'FINDINGS'] }] }
						})
					)
				: null
		);
		getReview.mockImplementation(async (id: string) => twoSections(id, FRESH));
		const { component, container } = render(TemplatedReportTab, {});
		await tick();
		expect(await (component as unknown as Tab).openExisting(TEMPLATED)).toBe(true);
		await pause(400);
		expect(viewerOf(container)?.state.doc.toString()).toContain('The spleen measures 10 cm.');
		expect(railSections(container)).toEqual(['IMPRESSION', 'FINDINGS']);
	});
});
