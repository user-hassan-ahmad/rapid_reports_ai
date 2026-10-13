// Card redesign helpers (B-design): verdict fallbacks, short sources, head chips. SYNTHETIC data.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { assumption, card, draft, outcome, preview, result } from './fixtures';
import { actionOf, allValueRows, scopeDoubts, citeShort, decidingQuestion, headlineOf, issuerShort, recommendationBeyond, sourcesOf, verdictOf } from './format';

describe('verdictOf', () => {
	it('fallbacks: headline = first clause, action = first sentence, category none only for a normal outcome', () => {
		const p = preview({ proposal: null, draft_outcome: outcome({ classification: 'Homogeneous mass of 10 HU or less: consistent with a benign lesion.', recommendation: 'No further imaging required. Consider hormonal tests.' }) });
		expect(verdictOf(p)).toMatchObject({ category: 'neutral', headline: 'Homogeneous mass of 10 HU or less', action: 'No further imaging required', pill: 'No further imaging required' });
		const n = preview({ proposal: null, draft_outcome: outcome({ classification: 'CAD-RADS 0', recommendation: '', normal: true }) });
		expect(verdictOf(n)).toMatchObject({ category: 'none', pill: 'CAD-RADS 0' });
	});

	it('the backend fields win, and props override them', () => {
		const p = preview({ proposal: null, draft_outcome: outcome({ headline: 'Benign adenoma', action: 'No further imaging', category: 'none' }) });
		expect(verdictOf(p)).toMatchObject({ category: 'none', headline: 'Benign adenoma', action: 'No further imaging', pill: 'No further imaging' });
		expect(verdictOf(p, { category: 'refer', action: 'Refer' })).toMatchObject({ category: 'refer', pill: 'Refer' });
		expect(verdictOf(preview({ proposal: null, draft_outcome: outcome({ category: 'info' }) }))?.category).toBe('info');
	});

	it('does not apply, no outcome yet, and the tentative most likely', () => {
		expect(verdictOf(preview({ state: 'does_not_apply', proposal: null, exclusion: outcome({ classification: 'Not for under 35s: excluded' }) }))).toMatchObject({ category: 'not_applicable', pill: 'Does not apply', headline: 'Not for under 35s' });
		const open = preview({ proposal: null, missing: ['a', 'b'], asks: [{ input: 'a', label: 'A' }, { input: 'b', label: 'B' }] });
		expect(verdictOf(open)).toMatchObject({ category: 'open', pill: '2 questions open' });
		expect(verdictOf(preview({ proposal: null, possible: ['x', 'y', 'z'] }))?.pill).toBe('3 outcomes possible');
		expect(verdictOf(preview({ proposal: null, most_likely: { headline: 'CT surveillance', category: 'surveillance' } }))).toMatchObject({ category: 'surveillance', pill: 'Likely: CT surveillance', tentative: true });
		expect(verdictOf(null)).toBeNull();
	});

	it('headlineOf caps at 8 words; actionOf takes the first sentence', () => {
		expect(headlineOf('one two three four five six seven eight nine ten: rest')).toBe('one two three four five six seven eight…');
		expect(actionOf('CT at 3 months. Then yearly.')).toBe('CT at 3 months');
	});
});

describe('sources', () => {
	const ese = { title: 'European Society of Endocrinology clinical practice guidelines', issuer: 'European Society of Endocrinology', edition: '2023' };
	it('issuerShort: initials, or the bracketed abbreviation', () => {
		expect(issuerShort('European Society of Endocrinology')).toBe('ESE');
		expect(issuerShort('National Institute for Health and Care Excellence (NICE)')).toBe('NICE');
		expect(issuerShort('Fleischner')).toBe('Fleischner');
	});
	it('citeShort: issuer + year + locator', () => {
		expect(citeShort({ ...ese, page: 18, section: 'Figure 5' })).toBe('ESE 2023 · Fig 5, p. 18');
		expect(citeShort({ title: 'Some Guideline Title Here', page: 3 })).toBe('Some Guideline Title · p. 3');
	});
	it('sourcesOf merges identical citations: one short line, the count of the others, the full list', () => {
		const s = sourcesOf([{ ...ese, page: 18, section: 'Figure 5' }, { ...ese, page: 17, section: 'Figure 4 note 3' }, { ...ese, page: 18, section: 'Figure 5' }, { ...ese, page: 24, section: 'R.4.2' }]);
		expect(s.short).toBe('ESE 2023 · Fig 5, p. 18');
		expect(s.more).toBe(2);
		expect(s.full).toHaveLength(3);
		expect(sourcesOf([])).toEqual({ short: '', more: 0, full: [] });
	});
});

describe('value list, recommendation and decidingQuestion', () => {
	it('allValueRows: assumed first, then pre-filled (exam presets too), then read, answered, still open; waiting hidden; N/A last; decisive kept', () => {
		const r = result(card(), preview({
			proposal: null,
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm' }),
				draft({ input: 'q', label: 'Open', state: 'asked', needed: true }),
				draft({ input: 'hu', label: 'HU', state: 'prefilled', value: '8 HU' }),
				draft({ input: 'na', label: 'N/A row', state: 'not_applicable' }),
				draft({ input: 'phase', label: 'Phase', state: 'prefilled', value: 'Unenhanced', by: 'exam' }),
				draft({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No', decisive: true }),
				draft({ input: 'age', label: 'Age', state: 'answered', value: '60' }),
				draft({ input: 'w', label: 'Waiting', state: 'asked', waiting: true })
			]
		}));
		const rows = allValueRows(r);
		expect(rows.map((x) => x.input)).toEqual(['cancer', 'hu', 'phase', 'size', 'age', 'q', 'na']);
		expect(rows[0].decisive).toBe(true);
		expect('decisive' in rows[1]).toBe(false); // absent unless the backend says
	});

	it('allValueRows takes decisive and the sign kind from the backend assumptions; "" display fields fall back', () => {
		const r = result(card(), preview({
			proposal: null,
			draft: [draft({ input: 'cancer', label: 'Known cancer', state: 'assumed', value: 'No' }), draft({ input: 'calc', label: 'Calcification', state: 'assumed', value: 'Absent' })],
			assumptions: [assumption('cancer', 'Known cancer', 'No', { decisive: false }), assumption('calc', 'Calcification', 'Absent', { kind: 'sign', decisive: null })]
		}));
		const rows = allValueRows(r);
		expect(rows.map((x) => [x.input, x.decisive, x.sign ?? false])).toEqual([['cancer', false, false], ['calc', null, true]]);
		const blank = preview({ proposal: null, draft_outcome: outcome({ classification: 'Cat A: x', recommendation: 'Do y. Then z.', headline: '', action: '', category: '' }) });
		expect(verdictOf(blank)).toMatchObject({ category: 'neutral', headline: 'Cat A', action: 'Do y' });
	});

	it('scopeDoubts: the doubtful inputs with their label, value and options from the draft', () => {
		const p = preview({ proposal: null, scope_doubt: ['d'], draft: [draft({ input: 'd', label: 'Maximum diameter', state: 'prefilled', value: '35 mm', options: ['Not stated'] })] });
		expect(scopeDoubts(p)).toEqual([{ input: 'd', label: 'Maximum diameter', value: '35 mm', options: ['Not stated'] }]);
		expect(scopeDoubts(preview())).toEqual([]);
	});

	it('recommendationBeyond: only what the action does not already say', () => {
		expect(recommendationBeyond('No further imaging', 'No further imaging required.')).toBe('');
		expect(recommendationBeyond('CT at 3 months', 'CT at 3 months, then 1 year and 2 years if stable.')).toBe('then 1 year and 2 years if stable.');
		expect(recommendationBeyond('Refer · urology MDT', 'Refer to the urology MDT; surgery is usually advised.')).toBe('Refer to the urology MDT; surgery is usually advised.');
		expect(recommendationBeyond('', 'Some text.')).toBe('Some text.');
	});

	it('decidingQuestion: the deciding input label, else the first needed open question; empty with no branches', () => {
		const base = { proposal: null, draft: [draft({ input: 'brock', label: 'Brock risk', state: 'asked', needed: true }), draft({ input: 'x', label: 'Other', state: 'asked' })] };
		expect(decidingQuestion(preview({ ...base, deciding: [{ answer: 'a', headline: 'h' }], deciding_input: { input: 'x', label: 'Other' } }))).toBe('Other');
		expect(decidingQuestion(preview({ ...base, deciding: [{ answer: 'a', headline: 'h' }] }))).toBe('Brock risk');
		expect(decidingQuestion(preview({ ...base }))).toBe('');
	});
});

// WCAG contrast of the category text tokens on their pill wash (14% of the -line colour over the card surface)
describe('category text contrast', () => {
	const lum = (hex: string) => {
		const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
		return 0.2126 * r + 0.7152 * g + 0.0722 * b;
	};
	const ratio = (a: string, b: string) => {
		const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m);
		return (x + 0.05) / (y + 0.05);
	};
	const blend = (fg: string, bg: string, a: number) =>
		'#' + [1, 3, 5].map((i) => Math.round(parseInt(fg.slice(i, i + 2), 16) * a + parseInt(bg.slice(i, i + 2), 16) * (1 - a)).toString(16).padStart(2, '0')).join('');
	// read from disk: vitest stubs CSS imports (even ?raw) to an empty string
	const railCss = readFileSync(new URL('../../rail/rail.css', import.meta.url), 'utf8');
	const block = (sel: RegExp) => railCss.match(sel)![1];
	const token = (css: string, name: string) => css.match(new RegExp(`--rv-${name}:\\s*(#[0-9a-fA-F]{6})`))![1];
	const themes = { dark: { css: block(/\.rv-rail \{([^}]*)\}/), surface: '#141419' }, light: { css: block(/\.rv-rail\[data-theme='light'\] \{([^}]*)\}/), surface: '#ffffff' } };
	for (const [theme, t] of Object.entries(themes))
		for (const c of ['green', 'blue', 'amber', 'red'])
			it(`${theme} ${c} text >= 4.5:1 on its pill`, () => {
				const pill = blend(token(t.css, `${c}-line`), t.surface, 0.14);
				expect(ratio(token(t.css, `${c}-text`), pill)).toBeGreaterThanOrEqual(4.5);
			});
});
