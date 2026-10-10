import { describe, expect, it } from 'vitest';
import { dedupeSources } from './markdown';

describe('dedupeSources', () => {
	it('drops repeated links and labels a title shared by different links by its page', () => {
		// live b4e8e644: three NICE links all titled with the geo-block page title
		const t = 'CKS is only available in the UK | NICE';
		const out = dedupeSources([
			{ url: 'https://cks.nice.org.uk/topics/adrenal-incidentaloma/', title: t },
			{ url: 'https://cks.nice.org.uk/topics/appendicitis/management/', title: t },
			{ url: 'https://cks.nice.org.uk/topics/appendicitis/management', title: t },
			{ url: 'https://www.rcr.ac.uk/guidance', title: 'RCR guidance' }
		]);
		expect(out.map((s) => s.title)).toEqual([
			'Adrenal incidentaloma · cks.nice.org.uk',
			'Appendicitis management · cks.nice.org.uk',
			'RCR guidance'
		]);
	});

	it('keeps a unique title as it is', () => {
		expect(dedupeSources([{ url: 'https://a.org/x', title: 'X' }])[0].title).toBe('X');
	});
});
