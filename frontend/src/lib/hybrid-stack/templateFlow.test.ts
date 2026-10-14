import { describe, expect, it } from 'vitest';
import { templateVariables } from './templateFlow';

describe('template stack Generate: the variables', () => {
	it('sends every template input except FINDINGS (the server builds FINDINGS from the units)', () => {
		expect(templateVariables({ FINDINGS: 'Liver normal.', CLINICAL_HISTORY: 'Pain.', COMPARISON: 'None.' }))
			.toEqual({ CLINICAL_HISTORY: 'Pain.', COMPARISON: 'None.' });
		expect(templateVariables({})).toEqual({});
	});
	it('never mutates the form values', () => {
		const v = { FINDINGS: 'x', A: '1' };
		templateVariables(v);
		expect(v).toEqual({ FINDINGS: 'x', A: '1' });
	});
});
