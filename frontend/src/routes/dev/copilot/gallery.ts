// SYNTHETIC: the /dev/copilot gallery, one section per card state (Task A5). Pack names and generic phrases only.
import { card, draft, outcome, preview, reference, result } from '$lib/copilot/cards/fixtures';
import type { CardView } from '$lib/copilot/cards/view';
import { cardRef, type Finding, type Group } from '$lib/copilot/state';
import type { Card, OpenResult } from '$lib/copilot/types';

export interface Section {
	id: string;
	title: string;
	groups: Group[];
	views: Record<string, CardView>;
	matching?: boolean;
	matchFailed?: boolean;
	otherState?: 'idle' | 'loading' | 'done' | 'failed';
	/** Cards "Other guidelines" adds (this section only). */
	others?: { card: Card; result: OpenResult | null; error?: string }[];
}

const f = (n: number, text: string, region = 'LUNGS'): Finding => ({ id: `u${n}`, unitId: n, text, region });
const nodule = f(1, '7 mm solid nodule, right lower lobe');
const thyroid = f(2, '1.8 cm left thyroid nodule', 'THYROID');
const mass = f(3, '4 cm right upper lobe mass');
const cyst = f(4, '3 cm cystic lesion, left kidney', 'KIDNEYS');
const white = f(5, 'Periventricular white matter changes', 'BRAIN');

const view = (r: OpenResult | null, over: Partial<CardView> = {}): CardView => ({ open: false, loading: false, error: null, result: r, ...over });
const one = (finding: Finding | null, c: Card, v: CardView): Pick<Section, 'groups' | 'views'> => ({
	groups: [{ finding, cards: [c] }],
	views: { [cardRef(c)]: v }
});

const cad = card({ key: 'cad-rads-2', name: 'CAD-RADS 2.0', version: '2.0', finding_id: 'exam', finding: 'Coronary CT angiography' });
const cadQuiet = result(cad, preview({ proposal: null, draft_outcome: outcome({ classification: 'CAD-RADS 0', recommendation: 'No further cardiac investigation.', normal: true }) })); // Task 3: draft_outcome.normal
const cadExam = result(
	cad,
	preview({
		proposal: outcome({ classification: 'CAD-RADS 3', recommendation: 'Consider functional assessment.', normal: false }),
		settled: [{ input: 'modifier', value: 'none', quote: '', fact: '', by: 'exam' }]
	})
);

const fl = card({ finding: nodule.text });
const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015', version: '2015', finding: nodule.text });
const flSib = card({ finding: nodule.text, siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
const bosniak = card({ key: 'bosniak-renal-cyst', name: 'Bosniak 2019', version: '2019', finding_id: 'u4', finding: cyst.text });
const bta = card({ key: 'bta-thyroid-u-grading', name: 'BTA U grading', version: '2014', finding_id: 'u2', finding: thyroid.text, needs_modality: 'US' });
const adrenal = f(6, '2.2 cm left adrenal nodule', 'ADRENALS');
const ese = card({ key: 'ese-adrenal-incidentaloma', name: 'ESE adrenal incidentaloma', version: '2023', finding_id: 'u6', finding: adrenal.text });
// check_first in Task 3's shape (B1): values drafted (read, pre-filled, exam preset), eligibility assumed, one input
// still open, one waiting (hidden); proposal is always null for packs, the outcome is draft_outcome.
const eseCheck = result(
	ese,
	preview({
		state: 'check_first',
		proposal: null,
		draft_outcome: outcome({ classification: 'Benign adenoma (unenhanced ≤ 10 HU)', recommendation: 'No further imaging for this nodule.', caveats: [] }),
		draft: [
			draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm left adrenal nodule' }),
			draft({ input: 'unenhanced_hu', label: 'Unenhanced attenuation', state: 'prefilled', value: '8 HU', quote: 'measuring 8 HU', why: ['attenuation not stated as unenhanced'] }),
			draft({ input: 'age', label: 'Age', scope: 'patient', fact: 'age', state: 'read', value: '65', quote: '65 year old' }),
			draft({ input: 'phase', label: 'Phase', state: 'prefilled', value: 'unenhanced CT', by: 'exam', why: ['set by the exam'] }),
			draft({ input: 'known_cancer', label: 'Known extra-adrenal cancer', role: 'eligibility', scope: 'patient', state: 'assumed', value: 'No', why: ['assumed: not stated, so taken as within the guideline\'s scope'] }),
			draft({ input: 'hormone_excess', label: 'Clinical signs of hormone excess', role: 'eligibility', scope: 'patient', state: 'assumed', value: 'No' }),
			draft({ input: 'bilateral', label: 'Bilateral adrenal masses', role: 'eligibility', state: 'assumed', value: 'No' }),
			draft({ input: 'prior_imaging', label: 'Growth on prior imaging', state: 'asked', needed: true }),
			draft({ input: 'growth_rate', label: 'Growth rate', state: 'asked', waiting: true })
		],
		assumptions: ['known_cancer', 'hormone_excess', 'bilateral'],
		assumed_eligible: true,
		missing: ['prior_imaging'],
		waiting: ['growth_rate'],
		asks: [{ input: 'prior_imaging', label: 'Growth on prior imaging', role: 'clinical' }]
	})
);
// applies in Task 3's shape: a pre-filled size (another number in the finding), a read type, an N/A input
const flDraft = result(
	fl,
	preview({
		proposal: null,
		draft_outcome: outcome({ classification: 'Optional CT at 12 months', recommendation: 'Low-risk patient: optional CT at 12 months.' }),
		draft: [
			draft({ input: 'size', label: 'Mean diameter', state: 'prefilled', value: '7 mm', quote: '7 mm solid nodule', why: ['another number in this finding'] }),
			draft({ input: 'type', label: 'Nodule type', state: 'read', value: 'Solid', quote: 'solid nodule' }),
			draft({ input: 'count', label: 'Number of nodules', state: 'read', value: 'Single', quote: 'nodule' }),
			draft({ input: 'subsolid_part', label: 'Solid component', state: 'not_applicable' })
		]
	})
);
const tnm = card({ key: 'tnm-lung', name: 'TNM 9 · Lung', version: '9', finding_id: 'u3', finding: mass.text });
const tier2 = card({ key: 'fazekas', name: 'Fazekas scale', version: '1987', finding_id: 'u5', finding: white.text, reference: true });

const tnmResult = result(tnm, null, {
	entry: {
		...result(tnm, null).entry!,
		content: {
			applies_to: '',
			summary: 'TNM 9 staging of lung tumours.',
			branches: [
				{
					name: 'Staging',
					rule: '',
					inputs: [
						{ id: 't', question: 'T category', options: ['TX', 'T1', 'T2', 'T3', 'T4'] },
						{ id: 'n', question: 'N category', options: ['NX', 'N0', 'N1', 'N2', 'N3'] },
						{ id: 'm', question: 'M category', options: ['M0', 'M1'] }
					]
				}
			]
		}
	}
});

const flApplies = result(fl, preview({ proposal: outcome({ classification: 'Optional CT at 12 months', caveats: ['A generic caveat.'] }) }), { reference });

export const sections: Section[] = [
	{ id: 'matching', title: 'First match in flight', groups: [], views: {}, matching: true },
	{ id: 'match-failed', title: 'Match failed', groups: [], views: {}, matchFailed: true },
	{ id: 'empty', title: 'No guideline applies yet', groups: [], views: {} },
	{ id: 'quiet', title: 'Exam card, quiet line', ...one(null, cad, view(cadQuiet)) },
	{ id: 'exam-set', title: 'Exam card, set by the exam', ...one(null, cad, view(cadExam)) },
	{ id: 'applies', title: 'Pack, applies (open)', ...one(nodule, fl, view(flApplies, { open: true })) },
	{ id: 'possible', title: 'Pack, applies with no outcome yet', ...one(nodule, fl, view(result(fl, preview({ proposal: null, possible: ['Category A', 'Category B'] })), { open: true })) },
	{ id: 'check-first-values', title: 'Check first: values, assumed checks, still open', ...one(adrenal, ese, view(eseCheck, { open: true })) },
	{ id: 'draft-values', title: 'Draft values: read, pre-filled, N/A', ...one(nodule, fl, view(flDraft, { open: true })) },
	{
		id: 'check-first',
		title: 'Pack, check first',
		...one(cyst, bosniak, view(result(bosniak, preview({ state: 'check_first', proposal: null, missing: ['enhancement'], asks: [{ input: 'enhancement', label: 'Measurable enhancement' }] })), { open: true }))
	},
	{
		id: 'does-not-apply',
		title: 'Pack, does not apply',
		...one(nodule, fl, view(result(fl, preview({ state: 'does_not_apply', proposal: null, exclusion: outcome({ classification: 'Not for patients under 35', recommendation: '' }) })), { open: true }))
	},
	{ id: 'degraded', title: 'Pack, degraded', ...one(nodule, fl, view(result(fl, preview({ degraded: true })), { open: true })) },
	{ id: 'collapsed', title: 'Pack, collapsed with preview', ...one(nodule, fl, view(flApplies)) },
	{
		id: 'siblings',
		title: 'Siblings, stacked in the rail',
		...one(
			nodule,
			flSib,
			view(null, {
				open: true,
				columns: {
					[fl.key]: { loading: false, error: null, result: flApplies },
					[bts.key]: { loading: false, error: null, result: result(bts, preview({ state: 'check_first', proposal: null, missing: ['risk'], asks: [{ input: 'risk', label: 'Risk score' }] })) }
				}
			})
		)
	},
	{ id: 'needs-modality', title: 'Needs another modality', ...one(thyroid, bta, view(null)) },
	{ id: 'reference', title: 'Reference card (tier 2)', ...one(white, tier2, view(result(tier2, null, { reference }), { open: true })) },
	{ id: 'tnm', title: 'TNM, read-only', ...one(mass, tnm, view(tnmResult, { open: true })) },
	{ id: 'loading', title: 'Card loading', ...one(nodule, fl, view(null, { open: true, loading: true })) },
	{ id: 'error', title: "Card couldn't open", ...one(nodule, fl, view(null, { open: true, error: 'timeout' })) },
	{ id: 'still-loading', title: 'Card still loading', ...one(nodule, fl, view(null, { open: true, error: 'loading' })) },
	{
		id: 'other',
		title: 'Other guidelines',
		...one(nodule, fl, view(flApplies)),
		otherState: 'idle',
		others: [
			{ card: card({ key: 'web-nodule-guide', name: 'A society nodule guide', version: '', finding: nodule.text, known: false, status: 'new' }), result: null, error: 'unavailable' }
		]
	},
	{ id: 'other-failed', title: 'Other guidelines failed', ...one(nodule, fl, view(flApplies)), otherState: 'failed' }
];

/** Every section's cards at once, for the CopilotRail preview. */
export const wholeCase: Pick<Section, 'groups' | 'views'> = {
	groups: [
		{ finding: null, cards: [cad] },
		{ finding: nodule, cards: [flSib] },
		{ finding: thyroid, cards: [bta] },
		{ finding: mass, cards: [tnm] },
		{ finding: cyst, cards: [bosniak] },
		{ finding: adrenal, cards: [ese] },
		{ finding: white, cards: [tier2] }
	],
	views: {
		[cardRef(cad)]: view(cadQuiet),
		[cardRef(flSib)]: view(null, {
			columns: {
				[fl.key]: { loading: false, error: null, result: flApplies },
				[bts.key]: { loading: false, error: null, result: result(bts, preview()) }
			}
		}),
		[cardRef(tnm)]: view(tnmResult),
		[cardRef(bosniak)]: view(result(bosniak, preview({ state: 'check_first', proposal: null, missing: ['enhancement'], asks: [{ input: 'enhancement', label: 'Measurable enhancement' }] }))),
		[cardRef(tier2)]: view(result(tier2, null, { reference })),
		[cardRef(ese)]: view(eseCheck, { open: true })
	}
};
