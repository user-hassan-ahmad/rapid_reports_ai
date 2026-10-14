import { describe, expect, it } from 'vitest';
import { offeredAndDropped } from './gate';

describe('offeredAndDropped', () => {
	it('records what was offered and what the check dropped, with the reason', () => {
		const input = { Liver: ['A.', 'B.'] };
		const out = offeredAndDropped(input, { Liver: [{ sentence: 'B.', reason: 'contradicted' }] });
		expect(out.offered).toEqual({ Liver: ['A.', 'B.'] });
		expect(out.offered).not.toBe(input);
		expect(out.jev_dropped).toEqual({ Liver: [{ sentence: 'B.', reason: 'contradicted' }] });
	});
	it('records nothing dropped when the check returned no drops', () => {
		expect(offeredAndDropped({ Liver: ['A.'] }, undefined).jev_dropped).toEqual({});
	});
	it('says so when the check failed, rather than recording no drops', () => {
		const out = offeredAndDropped({ Liver: ['A.'] }, undefined, true);
		expect(out).toEqual({ offered: { Liver: ['A.'] }, jev_dropped: null, assumed_check_failed: true });
	});
});
