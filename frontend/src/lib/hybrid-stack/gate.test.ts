import { describe, expect, it } from 'vitest';
import { offeredAndDropped } from './gate';

describe('offeredAndDropped', () => {
	it('records what was offered and what the check dropped, with the reason', () => {
		const out = offeredAndDropped({ Liver: ['A.', 'B.'] }, { Liver: [{ sentence: 'B.', reason: 'contradicted' }] });
		expect(out.offered).toEqual({ Liver: ['A.', 'B.'] });
		expect(out.jev_dropped).toEqual({ Liver: [{ sentence: 'B.', reason: 'contradicted' }] });
	});
	it('records nothing dropped when the check returned no drops', () => {
		expect(offeredAndDropped({ Liver: ['A.'] }, undefined).jev_dropped).toEqual({});
	});
});
