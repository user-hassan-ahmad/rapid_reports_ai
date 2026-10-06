import { EditorState } from '@codemirror/state';
import { describe, expect, it } from 'vitest';
import { applyEditText, toChanges, type EditLike } from './edits';

// Parity vectors: each `expected` is the backend's verifier.apply_edit(doc, Edit(**edit), sections) output
// (None → null), generated from backend/src/rapid_reports_ai/review_engine/verifier.py. The inputs are the
// backend tests' own (test_review_engine_verifier.py, test_review_engine_preapply.py) plus edge cases.
interface Vector {
	name: string;
	doc: string;
	edit: EditLike;
	sections: string[] | null;
	expected: string | null;
}

const VECTORS: Vector[] = [
	{
		name: 'replace',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. There is a 14 mm cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'upgrade',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'upgrade', find: 'a cyst', replace: 'a 14 mm simple cyst' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. There is a 14 mm simple cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'replace with $& in text',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'replace', find: 'a cyst', replace: 'a $& cyst' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. There is a $& cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'replace not unique',
		doc: 'The liver is normal. The spleen is normal.',
		edit: { mode: 'replace', find: 'normal', replace: 'x' },
		sections: null,
		expected: null
	},
	{
		name: 'replace absent',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'replace', find: 'pancreas', replace: 'x' },
		sections: null,
		expected: null
	},
	{
		name: 'replace overlapping twice',
		doc: 'normal normal',
		edit: { mode: 'replace', find: 'normal', replace: 'x' },
		sections: [],
		expected: null
	},
	{
		name: 'replace null replace',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'replace', find: 'a cyst', replace: null },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: null
	},
	{
		name: 'replace to empty',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'replace', find: ' There is a cyst in the left kidney.', replace: '' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nThe liver is normal.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'replace list item via production fix',
		doc: 'FINDINGS:\nThe liver is normal. No free fluid, pneumothorax or effusion. The spleen is normal.\nIMPRESSION:\nNormal.',
		edit: {
			mode: 'replace',
			find: 'No free fluid, pneumothorax or effusion.',
			replace: 'No free fluid or effusion.'
		},
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. No free fluid or effusion. The spleen is normal.\nIMPRESSION:\nNormal.'
	},
	{
		name: 'remove with trailing space',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'remove', find: 'The liver is normal. ' },
		sections: null,
		expected: 'FINDINGS:\nThere is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'remove leading sentence',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'remove', find: 'The liver is normal.' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nThere is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'remove whole line',
		doc: 'FINDINGS:\nThe liver is normal.\nThe  spleen is normal.\nIMPRESSION:\nNormal.',
		edit: { mode: 'remove', find: 'The liver is normal.' },
		sections: null,
		expected: 'FINDINGS:\nThe  spleen is normal.\nIMPRESSION:\nNormal.'
	},
	{
		name: 'remove middle keeps other spacing',
		doc: 'FINDINGS:\nA.  B. C is here. D is there.\nIMPRESSION:\nNormal.',
		edit: { mode: 'remove', find: 'C is here.' },
		sections: null,
		expected: 'FINDINGS:\nA.  B. D is there.\nIMPRESSION:\nNormal.'
	},
	{
		name: 'remove last on line',
		doc: 'FINDINGS:\nA.  B. C is here. D is there.\nIMPRESSION:\nNormal.',
		edit: { mode: 'remove', find: 'D is there.' },
		sections: null,
		expected: 'FINDINGS:\nA.  B. C is here.\nIMPRESSION:\nNormal.'
	},
	{
		name: 'remove mid-sentence seam',
		doc: 'FINDINGS:\nOne. Two is here. Three.',
		edit: { mode: 'remove', find: 'Two is here.' },
		sections: null,
		expected: 'FINDINGS:\nOne. Three.'
	},
	{
		name: 'remove mid-word end',
		doc: 'FINDINGS:\nThe liver is normal. No gallstones. The spleen is normal.',
		edit: { mode: 'remove', find: 'is normal. No gall' },
		sections: null,
		expected: null
	},
	{
		name: 'remove mid-word start',
		doc: 'FINDINGS:\nThe liver is normal. No gallstones. The spleen is normal.',
		edit: { mode: 'remove', find: 'iver is normal. ' },
		sections: null,
		expected: null
	},
	{
		name: 'remove word-aligned',
		doc: 'FINDINGS:\nThe liver is normal. No gallstones. The spleen is normal.',
		edit: { mode: 'remove', find: 'No gallstones. ' },
		sections: null,
		expected: 'FINDINGS:\nThe liver is normal. The spleen is normal.'
	},
	{
		name: 'remove numbered item at end',
		doc: 'FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\nIMPRESSION:\n1. Normal liver.\n2. No free fluid.',
		edit: { mode: 'remove', find: 'No free fluid.' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\nIMPRESSION:\n1. Normal liver.'
	},
	{
		name: 'remove numbered item renumbers',
		doc: 'IMPRESSION:\n1. A is here.\n2. B is here.\n3. C is here.',
		edit: { mode: 'remove', find: 'B is here.' },
		sections: ['IMPRESSION'],
		expected: 'IMPRESSION:\n1. A is here.\n2. C is here.'
	},
	{
		name: 'remove first numbered item renumbers all',
		doc: 'IMPRESSION:\n1. A is here.\n2. B is here.\n3. C is here.\n4. D.',
		edit: { mode: 'remove', find: 'A is here.' },
		sections: ['IMPRESSION'],
		expected: 'IMPRESSION:\n1. B is here.\n2. C is here.\n3. D.'
	},
	{
		name: 'remove numbered item with paren marker',
		doc: 'IMPRESSION:\n1) A.\n2) B.\n3) C.',
		edit: { mode: 'remove', find: 'B.' },
		sections: ['IMPRESSION'],
		expected: 'IMPRESSION:\n1) A.\n2) C.'
	},
	{
		name: 'remove bullet item',
		doc: 'FINDINGS:\n- A is here.\n- B is here.\n- C is here.',
		edit: { mode: 'remove', find: 'B is here.' },
		sections: [],
		expected: 'FINDINGS:\n- A is here.\n- C is here.'
	},
	{
		name: 'remove whole paragraph keeps one blank',
		doc: 'FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\nIMPRESSION:\n1. Normal liver.\n2. No free fluid.',
		edit: { mode: 'remove', find: 'There is no free fluid. The spleen is normal.' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nThe liver is normal.\n\nIMPRESSION:\n1. Normal liver.\n2. No free fluid.'
	},
	{
		name: 'remove leaves punctuation behind',
		doc: 'FINDINGS:\nLiver normal. No fluid . Spleen normal.',
		edit: { mode: 'remove', find: 'No fluid' },
		sections: [],
		expected: 'FINDINGS:\nLiver normal. Spleen normal.'
	},
	{
		name: 'remove leading list item capitalises',
		doc: 'FINDINGS:\nNo effusion, no pneumothorax.\n',
		edit: { mode: 'remove', find: 'No effusion,' },
		sections: [],
		expected: 'FINDINGS:\nNo pneumothorax.\n'
	},
	{
		name: 'remove trailing clause closes sentence',
		doc: 'FINDINGS:\nNo effusion; no pneumothorax.\n',
		edit: { mode: 'remove', find: 'no pneumothorax.' },
		sections: [],
		expected: 'FINDINGS:\nNo effusion.\n'
	},
	{
		name: 'remove CRLF line',
		doc: 'FINDINGS:\r\nA. B.\r\nC.\r\nIMPRESSION:\r\nD.',
		edit: { mode: 'remove', find: 'C.' },
		sections: [],
		expected: 'FINDINGS:\r\nA. B.\r\nIMPRESSION:\r\nD.'
	},
	{
		name: 'remove CRLF numbered',
		doc: 'IMPRESSION:\r\n1. A.\r\n2. B.\r\n3. C.',
		edit: { mode: 'remove', find: 'B.' },
		sections: [],
		expected: 'IMPRESSION:\r\n1. A.\r\n2. C.'
	},
	{
		name: 'remove whole sentence production fix',
		doc: 'FINDINGS:\nThe liver is normal. No free fluid. The spleen is normal.\nIMPRESSION:\nNormal.',
		edit: { mode: 'remove', find: 'No free fluid.' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nThe liver is normal. The spleen is normal.\nIMPRESSION:\nNormal.'
	},
	{
		name: 'remove last line of doc',
		doc: 'FINDINGS:\nA.\nB.',
		edit: { mode: 'remove', find: 'B.' },
		sections: [],
		expected: 'FINDINGS:\nA.'
	},
	{
		name: 'remove only numbered item last',
		doc: 'IMPRESSION:\n1. A.',
		edit: { mode: 'remove', find: 'A.' },
		sections: [],
		expected: 'IMPRESSION:'
	},
	{
		name: 'remove not unique',
		doc: 'A. A.',
		edit: { mode: 'remove', find: 'A.' },
		sections: [],
		expected: null
	},
	{
		name: 'remove mid comma clause',
		doc: 'FINDINGS:\nLiver, spleen, kidneys normal.',
		edit: { mode: 'remove', find: 'spleen,' },
		sections: [],
		expected: 'FINDINGS:\nLiver, kidneys normal.'
	},
	{
		name: 'remove clause before semicolon',
		doc: 'FINDINGS:\nNo effusion, no ascites; normal liver.',
		edit: { mode: 'remove', find: 'no ascites' },
		sections: [],
		expected: 'FINDINGS:\nNo effusion; normal liver.'
	},
	{
		name: 'insert after sentence',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: 'The liver is normal.', replace: 'The spleen is normal.' },
		sections: null,
		expected:
			'FINDINGS:\nThe liver is normal. The spleen is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'insert after anchor with trailing space',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: 'The liver is normal. ', replace: 'The spleen is normal.' },
		sections: null,
		expected:
			'FINDINGS:\nThe liver is normal. The spleen is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'insert after partial word',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: 'The liver is norm', replace: 'X.' },
		sections: null,
		expected: null
	},
	{
		name: 'insert after heading',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: 'FINDINGS:', replace: 'The spleen is normal.' },
		sections: null,
		expected:
			'FINDINGS:\nThe spleen is normal.\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'insert after mixed-case known heading',
		doc: 'Findings:\nThe liver is normal.',
		edit: { mode: 'insert', after: 'Findings:', replace: 'X.' },
		sections: ['Findings'],
		expected: 'Findings:\nX.\nThe liver is normal.'
	},
	{
		name: 'insert after region sub-heading',
		doc: 'FINDINGS:\n\nHEAD:\nNo intracranial haemorrhage.\n\nCHEST:\nNo pneumothorax. Small left effusion.\n\nABDOMEN:\nThe liver is normal.\n\nIMPRESSION:\nSmall left effusion.',
		edit: { mode: 'insert', after: 'CHEST:', replace: 'Left rib fracture.' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\n\nHEAD:\nNo intracranial haemorrhage.\n\nCHEST:\nLeft rib fracture.\nNo pneumothorax. Small left effusion.\n\nABDOMEN:\nThe liver is normal.\n\nIMPRESSION:\nSmall left effusion.'
	},
	{
		name: 'insert after anchor not unique',
		doc: 'A. A.',
		edit: { mode: 'insert', after: 'A.', replace: 'B.' },
		sections: [],
		expected: null
	},
	{
		name: 'insert blank replace',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: 'The liver is normal.', replace: '  ' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: null
	},
	{
		name: 'insert blank anchor',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: '  ', replace: 'X.', section: 'FINDINGS' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: null
	},
	{
		name: 'insert replace is stripped',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', after: 'The liver is normal.', replace: '  Spleen normal.  ' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. Spleen normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'insert anchor at doc end',
		doc: 'FINDINGS:\nA.',
		edit: { mode: 'insert', after: 'A.', replace: 'B.' },
		sections: [],
		expected: 'FINDINGS:\nA. B.'
	},
	{
		name: 'append to IMPRESSION',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', replace: 'Follow-up is suggested.', section: 'IMPRESSION' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst. Follow-up is suggested.'
	},
	{
		name: 'append to Findings (case-insensitive)',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', replace: 'Spleen normal.', section: 'Findings' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney. Spleen normal.\nIMPRESSION:\nLeft renal cyst.'
	},
	{
		name: 'append to unknown section',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', replace: 'X.', section: 'TECHNIQUE' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: null
	},
	{
		name: 'append without section',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'insert', replace: 'X.' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: null
	},
	{
		name: 'append to empty section',
		doc: 'FINDINGS:\nThe liver is normal.\nIMPRESSION:\n',
		edit: { mode: 'insert', replace: 'Normal study.', section: 'IMPRESSION' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNormal study.\n'
	},
	{
		name: 'append to numbered IMPRESSION',
		doc: 'FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\nIMPRESSION:\n1. Normal liver.\n2. No free fluid.',
		edit: { mode: 'insert', replace: 'Follow-up advised.', section: 'IMPRESSION' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\nIMPRESSION:\n1. Normal liver.\n2. No free fluid.\n3. Follow-up advised.'
	},
	{
		name: 'append to numbered IMPRESSION CRLF',
		doc: 'FINDINGS:\r\nA.\r\nIMPRESSION:\r\n1. B.\r\n2. C.\r\n',
		edit: { mode: 'insert', replace: 'D.', section: 'IMPRESSION' },
		sections: [],
		expected: 'FINDINGS:\r\nA.\r\nIMPRESSION:\r\n1. B.\r\n2. C.\r\n3. D.\r\n'
	},
	{
		name: 'append to section with region sub-headings',
		doc: 'FINDINGS:\n\nHEAD:\nNo intracranial haemorrhage.\n\nCHEST:\nNo pneumothorax. Small left effusion.\n\nABDOMEN:\nThe liver is normal.\n\nIMPRESSION:\nSmall left effusion.',
		edit: { mode: 'insert', replace: 'Rib fracture on the left.', section: 'FINDINGS' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected:
			'FINDINGS:\n\nHEAD:\nNo intracranial haemorrhage.\n\nCHEST:\nNo pneumothorax. Small left effusion.\n\nABDOMEN:\nThe liver is normal. Rib fracture on the left.\n\nIMPRESSION:\nSmall left effusion.'
	},
	{
		name: 'append to FINDINGS with blank line before next',
		doc: 'FINDINGS:\nA. B.\n\nIMPRESSION:\nC.',
		edit: { mode: 'insert', replace: 'D.', section: 'FINDINGS' },
		sections: null,
		expected: 'FINDINGS:\nA. B. D.\n\nIMPRESSION:\nC.'
	},
	{
		name: 'append fallback heading detection no sections',
		doc: 'FINDINGS:\nA.\nIMPRESSION:\nB.',
		edit: { mode: 'insert', replace: 'C.', section: 'IMPRESSION' },
		sections: null,
		expected: 'FINDINGS:\nA.\nIMPRESSION:\nB. C.'
	},
	{
		name: 'append heading without colon needs known names',
		doc: 'FINDINGS\nA.\nIMPRESSION\nB.',
		edit: { mode: 'insert', replace: 'C.', section: 'IMPRESSION' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS\nA.\nIMPRESSION\nB. C.'
	},
	{
		name: 'append heading without colon unknown',
		doc: 'FINDINGS\nA.\nIMPRESSION\nB.',
		edit: { mode: 'insert', replace: 'C.', section: 'IMPRESSION' },
		sections: null,
		expected: null
	},
	{
		name: 'preapply insert_from_line',
		doc: 'FINDINGS:\nLiver normal. Spleen normal.\nIMPRESSION:\nNormal.',
		edit: {
			mode: 'insert',
			after: 'Spleen normal.',
			replace: 'Small left renal cyst.',
			section: 'FINDINGS'
		},
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nLiver normal. Spleen normal. Small left renal cyst.\nIMPRESSION:\nNormal.'
	},
	{
		name: 'closing label anchor',
		doc: 'FINDINGS:\nLungs clear.\n\nABDOMEN:\n\nIMPRESSION:\nNormal.',
		edit: { mode: 'insert', after: 'ABDOMEN:', replace: 'Small ascites.', section: 'FINDINGS' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: 'FINDINGS:\nLungs clear.\n\nABDOMEN:\nSmall ascites.\n\nIMPRESSION:\nNormal.'
	},
	{
		name: 'unknown mode-ish: remove without find',
		doc: 'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.',
		edit: { mode: 'remove' },
		sections: ['FINDINGS', 'IMPRESSION'],
		expected: null
	}
];

function applySpec(doc: string, spec: { from: number; to: number; insert: string }): string {
	return doc.slice(0, spec.from) + spec.insert + doc.slice(spec.to);
}

describe('applyEditText: backend apply_edit parity', () => {
	it.each(VECTORS)('$name', ({ doc, edit, sections, expected }) => {
		expect(applyEditText(doc, edit, sections ?? undefined)).toBe(expected);
	});
});

describe('toChanges: one ChangeSpec that reproduces the backend output', () => {
	it.each(VECTORS)('$name', ({ doc, edit, sections, expected }) => {
		const spec = toChanges(doc, edit, sections ?? undefined);
		if (expected === null) {
			expect(spec).toBeNull();
			return;
		}
		expect(spec).not.toBeNull();
		expect(applySpec(doc, spec!)).toBe(expected);
		if (!doc.includes('\r')) {
			// CM6 normalises CRLF, so only LF documents go through a real transaction
			const state = EditorState.create({ doc });
			expect(state.update({ changes: spec! }).state.doc.toString()).toBe(expected);
		}
	});
});

describe('toChanges: the change covers only the edit site', () => {
	const REPORT =
		'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.';

	it('replace is exactly the find span', () => {
		const from = REPORT.indexOf('a cyst');
		expect(toChanges(REPORT, { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' })).toEqual(
			{
				from,
				to: from + 'a cyst'.length,
				insert: 'a 14 mm cyst'
			}
		);
	});

	it('insert after an anchor is a point insert with one space', () => {
		const at = REPORT.indexOf('The liver is normal.') + 'The liver is normal.'.length;
		expect(
			toChanges(REPORT, {
				mode: 'insert',
				after: 'The liver is normal.',
				replace: 'The spleen is normal.'
			})
		).toEqual({ from: at, to: at, insert: ' The spleen is normal.' });
	});

	it('insert after a heading goes on the next line', () => {
		const at = 'FINDINGS:'.length;
		expect(toChanges(REPORT, { mode: 'insert', after: 'FINDINGS:', replace: 'X.' })).toEqual({
			from: at,
			to: at,
			insert: '\nX.'
		});
	});

	it('section append lands at the end of the section body', () => {
		const at = REPORT.indexOf('\nIMPRESSION:');
		expect(
			toChanges(REPORT, { mode: 'insert', replace: 'Spleen normal.', section: 'FINDINGS' }, [
				'FINDINGS',
				'IMPRESSION'
			])
		).toEqual({ from: at, to: at, insert: ' Spleen normal.' });
	});

	it('remove touches only the seam, never the rest of the document', () => {
		const doc = 'FINDINGS:\nOne. Two is here. Three.\nIMPRESSION:\nNormal.';
		const spec = toChanges(doc, { mode: 'remove', find: 'Two is here.' })!;
		expect(spec.insert).toBe('');
		expect(doc.slice(spec.from, spec.to).trim()).toBe('Two is here.');
	});

	it('a removed numbered item spans only its line and the renumbered lines below', () => {
		const doc = 'IMPRESSION:\n1. A is here.\n2. B is here.\n3. C is here.\n\nSigned.';
		const spec = toChanges(doc, { mode: 'remove', find: 'B is here.' }, ['IMPRESSION'])!;
		expect(spec.from).toBeGreaterThanOrEqual(doc.indexOf('1. A is here.') + '1. A is here.'.length);
		expect(spec.to).toBeLessThanOrEqual(doc.indexOf('\n\nSigned.'));
		expect(applySpec(doc, spec)).toBe('IMPRESSION:\n1. A is here.\n2. C is here.\n\nSigned.');
	});

	it('null for a missing edit or an unplaceable one', () => {
		expect(toChanges(REPORT, null)).toBeNull();
		expect(toChanges(REPORT, { mode: 'remove', find: 'iver is normal. ' })).toBeNull();
		expect(
			toChanges(REPORT, { mode: 'insert', after: 'The liver is norm', replace: 'X.' })
		).toBeNull();
	});
});
