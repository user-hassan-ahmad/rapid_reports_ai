import { describe, expect, it } from 'vitest';
import { appliedOptionIds, applyEdit, insertEdit, removeEdit, type ReportOption } from './impressionOptions';

const opt: ReportOption = { id: 'opt0', kind: 'recommendation', sentence: 'MRI brain is recommended.' };

const PROSE = `FINDINGS:
A mass.

IMPRESSION:
Metastatic cord compression at T7. Urgent neurosurgical review recommended.

Dr A Consultant Radiologist`;

const NUMBERED = `FINDINGS:
A mass.

IMPRESSION:
1. Cord compression at T7.
2. Urgent neurosurgical review recommended.
`;

describe('impression options', () => {
	it('appends to prose impressions after the last sentence, leaving a signature alone', () => {
		const out = applyEdit(PROSE, insertEdit(PROSE, opt)!);
		expect(out).toContain('Urgent neurosurgical review recommended. MRI brain is recommended.\n\nDr A');
	});

	it('continues a numbered impression', () => {
		const out = applyEdit(NUMBERED, insertEdit(NUMBERED, opt)!);
		expect(out).toContain('2. Urgent neurosurgical review recommended.\n3. MRI brain is recommended.');
	});

	it('round-trips: removing an inserted option restores the text', () => {
		for (const base of [PROSE, NUMBERED]) {
			const added = applyEdit(base, insertEdit(base, opt)!);
			expect(applyEdit(added, removeEdit(added, opt)!)).toBe(base);
		}
	});

	it('does not insert twice, and reports applied ids from the text', () => {
		const added = applyEdit(PROSE, insertEdit(PROSE, opt)!);
		expect(insertEdit(added, opt)).toBeNull();
		expect(appliedOptionIds(added, [opt, { ...opt, id: 'opt1', sentence: 'Absent.' }])).toEqual(['opt0']);
	});

	it('returns null without an impression section or an edited-away sentence', () => {
		expect(insertEdit('FINDINGS:\nA mass.', opt)).toBeNull();
		expect(removeEdit(PROSE, opt)).toBeNull();
	});

	it('stops the impression at the next section header', () => {
		const text = 'IMPRESSION:\nOne finding.\n\nRECOMMENDATIONS:\nSomething else.';
		expect(applyEdit(text, insertEdit(text, opt)!)).toContain('One finding. MRI brain is recommended.\n\nRECOMMENDATIONS:');
	});
});
