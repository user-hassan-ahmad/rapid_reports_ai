// SYNTHETIC: fixture cards and /open results for the card tests and the /dev/copilot gallery. Built from pack names
// and generic phrases only; no patient data.
import type { Card, DraftValue, OpenResult, Preview, Proposal, ReferenceView } from '../types';

export function card(over: Partial<Card> = {}): Card {
	return {
		key: 'fleischner-pulmonary-nodule',
		name: 'Fleischner 2017',
		version: '2017',
		finding_id: 'u1',
		why: '',
		branch: '',
		skeleton: [],
		publication: { title: '', body: '', year: '' },
		known: true,
		status: 'verified',
		siblings: [],
		reference: false,
		finding: 'Solid pulmonary nodule',
		needs_modality: '',
		...over
	};
}

export function outcome(over: Partial<Proposal> = {}): Proposal {
	return {
		classification: 'Category A',
		line: '',
		recommendation: 'Follow-up as per the guideline table.',
		caveats: [],
		citations: [{ source: 'S1', title: 'Guideline', edition: '2017', page: 3 }],
		...over
	};
}

export function preview(over: Partial<Preview> = {}): Preview {
	return {
		settled: [],
		missing: [],
		proposal: outcome(),
		state: 'applies',
		exclusion: null,
		possible: [],
		bounded: true,
		asks: [],
		trace: null,
		degraded: false,
		...over
	};
}

/** A Task 3 draft value (read by default). */
export function draft(over: Partial<DraftValue> = {}): DraftValue {
	return { input: 'x', label: 'X', role: 'clinical', scope: 'lesion', fact: '', state: 'read', value: '', quote: '', why: [], by: '', needed: false, waiting: false, options: [], ...over };
}

export const reference: ReferenceView = {
	summary: [{ id: 's1', text: 'A short summary of the guideline.', citation: { title: 'Guideline', page: 1 } }],
	definitions: [{ id: 'd1', text: 'Term: a generic definition.', citation: { title: 'Guideline', page: 2 } }],
	tables: [
		{ id: 't1', title: 'Categories', columns: ['Category', 'Meaning'], rows: [['A', 'First'], ['B', 'Second']], citation: { title: 'Guideline', table: 'Table 1' } }
	],
	pitfalls: [{ id: 'p1', text: 'A generic pitfall.', citation: { title: 'Guideline', section: 'Pitfalls' } }]
};

export function result(c: Card, p: Preview | null, over: Partial<OpenResult> = {}): OpenResult {
	return {
		entry: {
			key: c.key,
			name: c.name,
			version: c.version,
			status: 'verified',
			publication: { title: '', body: '', year: '' },
			content: { applies_to: '', summary: `${c.name}: a generic summary.`, branches: [] },
			sources: []
		},
		preview: p,
		branch: '',
		ms: 12,
		error: null,
		reference: null,
		needs_modality: '',
		...over
	};
}
