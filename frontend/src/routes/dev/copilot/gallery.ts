// SYNTHETIC: the /dev/copilot gallery, one section per card state (Task A5). Pack names and generic phrases only.
import { assumption, card, draft, outcome, preview, reference, result } from '$lib/copilot/cards/fixtures';
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
		assumptions: [assumption('known_cancer', 'Known extra-adrenal cancer'), assumption('hormone_excess', 'Clinical signs of hormone excess'), assumption('bilateral', 'Bilateral adrenal masses')],
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
// Hassan's checkpoint-3 screenshot case: ESE benign, with the pack's real outcome text, five caveats and four
// near-identical citations (one source, several locators). headline/action/category are the planned backend fields.
const eseSource = { source: 'S1', title: 'European Society of Endocrinology clinical practice guidelines on the management of adrenal incidentalomas', issuer: 'European Society of Endocrinology', edition: '2023' };
const eseBenign = result(
	ese,
	preview({
		state: 'check_first',
		proposal: null,
		draft_outcome: outcome({
			classification: 'Homogeneous adrenal mass of 10 HU or less on unenhanced CT: consistent with a benign (lipid-rich) lesion, whatever its size.',
			recommendation: 'No further imaging required.',
			headline: 'Benign adrenal adenoma',
			action: 'No further imaging',
			category: 'none',
			caveats: [
				'Clinical and hormonal assessment is still recommended: 1 mg overnight dexamethasone suppression test, and aldosterone/renin ratio if there is hypertension or unexplained hypokalaemia.',
				'Metanephrines are needed only when unenhanced attenuation is over 10 HU.',
				'Surgery is not recommended for an asymptomatic, non-functioning unilateral mass with obvious benign imaging features.',
				'In very young patients ESE would consider one follow-up scan at 12 months even for a presumably benign mass.',
				'Under 40 years (or in pregnancy), ESE recommends urgent assessment of any adrenal mass.'
			],
			citations: [
				{ ...eseSource, page: 18, section: 'Figure 5' },
				{ ...eseSource, page: 17, section: 'Figure 4 note 3' },
				{ ...eseSource, page: 18, section: 'Figure 5' },
				{ ...eseSource, page: 24, section: 'R.4.2' }
			]
		}),
		draft: [
			draft({ input: 'size_cm', label: 'Adrenal mass maximum diameter', state: 'read', value: '2.2 cm', quote: '2.2 cm left adrenal nodule' }),
			draft({ input: 'appearance', label: 'Appearance of the mass', state: 'read', value: 'Homogeneous', quote: 'homogeneous' }),
			draft({ input: 'unenhanced_hu', label: 'Attenuation on unenhanced CT', state: 'read', value: '8 HU', quote: 'measuring 8 HU on the unenhanced images' }),
			draft({ input: 'age', label: 'Age', scope: 'patient', fact: 'age', state: 'read', value: '65', quote: '65 year old' }),
			draft({ input: 'known_primary_cancer', label: 'History of extra-adrenal malignancy', role: 'eligibility', state: 'assumed', value: 'No' }),
			draft({ input: 'not_incidentaloma', label: 'Imaging for suspected adrenal disease', role: 'eligibility', state: 'assumed', value: 'No' }),
			draft({ input: 'calcification', label: 'Calcification', state: 'assumed', value: 'Absent' })
		],
		assumptions: [assumption('known_primary_cancer', 'History of extra-adrenal malignancy', 'No', { decisive: true }), assumption('not_incidentaloma', 'Imaging for suspected adrenal disease', 'No', { decisive: false }), assumption('calcification', 'Calcification', 'Absent', { kind: 'sign' })],
		assumed_eligible: true
	})
);
const btsSurv = result(
	bts,
	preview({
		proposal: null,
		draft_outcome: outcome({
			classification: 'Solid nodule 5 to 8 mm (Brock risk under 10%): CT surveillance.',
			recommendation: 'CT surveillance at 3 months, then 1 year and 2 years if stable.',
			headline: 'Solid nodule, low risk',
			action: 'CT at 3 months',
			category: 'surveillance',
			caveats: ['Use volumetry where available.'],
			citations: [{ title: 'BTS guidelines for the investigation and management of pulmonary nodules', issuer: 'British Thoracic Society', edition: '2015', page: 12, section: 'Algorithm 1' }]
		}),
		draft: [
			draft({ input: 'size', label: 'Mean diameter', state: 'read', value: '7 mm', quote: '7 mm solid nodule' }),
			draft({ input: 'type', label: 'Nodule type', state: 'read', value: 'Solid', quote: 'solid' }),
			draft({ input: 'brock', label: 'Brock risk', state: 'prefilled', value: '< 10%', why: ['the check did not run'] })
		]
	})
);
// no outcome yet, with the planned most_likely / deciding fields (BTS: Brock risk decides)
const btsLikely = result(
	bts,
	preview({
		proposal: null,
		draft_outcome: null,
		most_likely: { headline: 'CT surveillance', category: 'surveillance' },
		deciding_input: { input: 'brock', label: 'Brock risk' },
		deciding: [
			{ answer: 'Brock < 10%', headline: 'CT surveillance', category: 'surveillance' },
			{ answer: '10–70%', headline: 'PET-CT', category: 'workup' },
			{ answer: '> 70%', headline: 'Biopsy or excision', category: 'refer' }
		],
		possible: ['No follow-up', 'CT at 3 months', 'CT at 1 year', 'CT surveillance', 'PET-CT', 'Image-guided biopsy', 'Excision', 'Volumetry', 'Repeat CT', 'Discharge', 'MDT', 'Clinical review'],
		draft: [
			draft({ input: 'size', label: 'Mean diameter', state: 'read', value: '9 mm', quote: '9 mm solid nodule' }),
			draft({ input: 'type', label: 'Nodule type', state: 'read', value: 'Solid', quote: 'solid' }),
			draft({ input: 'age_ok', label: 'Age 18 or over', role: 'eligibility', state: 'assumed', value: 'Yes' }),
			draft({ input: 'brock', label: 'Brock risk', state: 'asked', needed: true })
		],
		assumptions: [assumption('age_ok', 'Age 18 or over', 'Yes')],
		assumed_eligible: true
	})
);
const bosniakRefer = result(
	bosniak,
	preview({
		proposal: null,
		draft_outcome: outcome({
			classification: 'Bosniak IV: cystic mass with one or more enhancing nodular components.',
			recommendation: 'Refer to the urology MDT; surgical management is usually advised.',
			headline: 'Bosniak IV cystic mass',
			action: 'Refer · urology MDT',
			category: 'refer',
			caveats: [],
			citations: [{ title: 'Bosniak Classification of Cystic Renal Masses, Version 2019', issuer: 'Society of Abdominal Radiology', edition: '2019', page: 5, table: 'Table 1' }]
		}),
		draft: [
			draft({ input: 'nodule', label: 'Enhancing nodule', state: 'read', value: 'Yes', quote: 'enhancing mural nodule' }),
			draft({ input: 'size', label: 'Size', state: 'read', value: '3 cm', quote: '3 cm cystic lesion' })
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
	{ id: 'ese-benign', title: 'ESE benign (checkpoint 3 case)', ...one(adrenal, ese, view(eseBenign, { open: true })) },
	{ id: 'bts-surveillance', title: 'BTS surveillance', ...one(nodule, bts, view(btsSurv, { open: true })) },
	{ id: 'refer', title: 'Refer', ...one(cyst, bosniak, view(bosniakRefer, { open: true })) },
	{
		id: 'info',
		title: 'Info: no management stated (CAD-RADS 4B/E)',
		...one(null, cad, view(result(cad, preview({ proposal: null, draft_outcome: outcome({ classification: 'CAD-RADS 4B/E: left main or three-vessel obstructive disease; exercise ECG not interpretable', recommendation: 'CAD-RADS assigns the grade; management follows the clinical team.', headline: 'CAD-RADS 4B/E', action: 'Report the grade', category: 'info', normal: false }) })), { open: true }))
	},
	{
		id: 'manage-as-solid',
		title: 'Outcome-level not applicable (Bosniak: not cystic)',
		...one(cyst, bosniak, view(result(bosniak, preview({ proposal: null, draft_outcome: outcome({ classification: 'Not a cystic mass: Bosniak does not classify solid masses.', recommendation: 'Manage as a solid renal mass (enhancing solid component).', headline: 'Not a cystic mass', action: 'Manage as solid renal mass', category: 'not_applicable' }) })), { open: true }))
	},
	{
		id: 'later-steps',
		title: 'Short action, full recommendation (Bosniak IIF)',
		...one(cyst, bosniak, view(result(bosniak, preview({ proposal: null, draft_outcome: outcome({ classification: 'Bosniak IIF: smooth minimally thickened wall or septa.', recommendation: 'Follow-up CT or MRI at 6 months and 12 months, then yearly for 5 years.', headline: 'Bosniak IIF', action: 'CT or MRI at 6 months', category: 'surveillance' }) })), { open: true }))
	},
	{ id: 'most-likely', title: 'No outcome yet: most likely, and what decides it', ...one(nodule, bts, view(btsLikely, { open: true })) },
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
	{
		id: 'does-not-apply-reason',
		title: 'Does not apply: the specific reason first (planned exclusion_reason)',
		...one(
			nodule,
			fl,
			view(
				result(
					fl,
					preview({
						state: 'does_not_apply',
						proposal: null,
						exclusion: outcome({ classification: 'Fleischner does not apply to patients under 35, with known cancer, or immunosuppressed, or to screening.', recommendation: '' }),
						exclusion_reason: { input: 'age', label: 'Age', value: '28' },
						draft: [
							draft({ input: 'age', label: 'Age', scope: 'patient', fact: 'age', state: 'read', value: '28', quote: '28 year old' }),
							draft({ input: 'size', label: 'Mean diameter', state: 'read', value: '7 mm', quote: '7 mm' }),
							draft({ input: 'subsolid', label: 'Solid component', state: 'not_applicable' })
						]
					})
				),
				{ open: true }
			)
		)
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
					[bts.key]: { loading: false, error: null, result: btsSurv }
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
				[bts.key]: { loading: false, error: null, result: btsSurv }
			}
		}),
		[cardRef(tnm)]: view(tnmResult),
		[cardRef(bosniak)]: view(result(bosniak, preview({ state: 'check_first', proposal: null, missing: ['enhancement'], asks: [{ input: 'enhancement', label: 'Measurable enhancement' }] }))),
		[cardRef(tier2)]: view(result(tier2, null, { reference })),
		[cardRef(ese)]: view(eseBenign, { open: true })
	}
};
