import { describe, expect, it } from 'vitest';
import type { StackUnit } from '$lib/hybrid-stack/types';
import { abnormalFindings, cardRef, groupCards, kindOf, markSent, norm, outcomeOf, planMatch, quiet, stableFindings, type Finding } from './state';
import type { Card, DraftValue, Preview, Proposal } from './types';

// SYNTHETIC: generic phrases and pack names only.
const unit = (id: number, text: string, o: Partial<StackUnit> = {}): StackUnit => ({
	id,
	text,
	group: 'Lungs',
	structure: null,
	attach_to: null,
	parts: null,
	covers: [],
	abnormal: true,
	pinned: false,
	heading: false,
	...o
});
const f = (unitId: number, text: string, id = `u${unitId}`): Finding => ({ id, unitId, text, region: 'Lungs' });
const card = (o: Partial<Card> = {}): Card => ({
	key: 'fleischner-2017',
	name: 'Fleischner',
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
	finding: 'a 6 mm solid nodule',
	needs_modality: '',
	...o
});
const prop = (classification: string): Proposal => ({ classification, line: '', recommendation: '', caveats: [], citations: [] });
const preview = (o: Partial<Preview> = {}): Preview => ({
	settled: [{ input: 'stenosis', value: '0', quote: 'no stenosis', fact: '', by: '' }],
	missing: [],
	proposal: prop('CAD-RADS 0'),
	state: 'applies',
	exclusion: null,
	possible: [],
	bounded: true,
	asks: [],
	trace: null,
	degraded: false,
	...o
});

describe('abnormalFindings', () => {
	it('lists abnormal placed items in dictation order with matcher ids', () => {
		const units = [
			unit(1, 'A 6 mm solid nodule.'),
			unit(2, 'Normal heart.', { abnormal: false }),
			unit(3, 'Liver heading', { heading: true }),
			unit(4, 'Unplaced bit.', { group: null }),
			unit(5, 'A cyst and a normal spleen.', {
				parts: [
					{ text: 'A 2 cm cyst', group: 'Liver', abnormal: true },
					{ text: 'a normal spleen', group: 'Spleen', abnormal: false }
				] as StackUnit['parts']
			})
		];
		expect(abnormalFindings(units)).toEqual([
			{ id: 'u1', unitId: 1, text: 'A 6 mm solid nodule.', region: 'Lungs' },
			{ id: 'u5.0', unitId: 5, text: 'A 2 cm cyst', region: 'Liver' }
		]);
	});
});

describe('stableFindings', () => {
	it('holds back a growing last unit while recording', () => {
		const prev = new Map([['u1', 'A 6 mm']]);
		expect(stableFindings(prev, [f(1, 'A 6 mm solid')], 1, true)).toEqual([]);
	});
	it('releases it once a later unit exists', () => {
		const prev = new Map([['u1', 'A 6 mm']]);
		expect(stableFindings(prev, [f(1, 'A 6 mm solid')], 2, true)).toHaveLength(1);
	});
	it('releases it once recording stops', () => {
		const prev = new Map([['u1', 'A 6 mm']]);
		expect(stableFindings(prev, [f(1, 'A 6 mm solid')], 1, false)).toHaveLength(1);
	});
	it('treats text unchanged across two rounds as stable', () => {
		const prev = new Map([['u1', 'A 6 mm solid nodule.']]);
		expect(stableFindings(prev, [f(1, 'A 6 mm solid nodule.')], 1, true)).toHaveLength(1);
	});
});

describe('markSent', () => {
	it('records each finding by normalised text, in place, and returns the same set', () => {
		const sent = new Set<string>(['old']);
		const out = markSent(sent, [f(1, '  A 6 mm  Solid nodule.'), f(2, 'A 2 cm cyst;')]);
		expect(out).toBe(sent);
		expect([...sent].sort()).toEqual(['a 2 cm cyst', 'a 6 mm solid nodule', 'old']);
		expect(markSent(sent, []).size).toBe(3);
	});
	it('marked texts no longer trigger a call under the same context', () => {
		const stable = [f(1, 'A 6 mm solid nodule.')];
		const sent = markSent(new Set(), stable);
		expect(planMatch(sent, 'ctx', 'ctx', stable, true).call).toBe(false);
	});
});

describe('planMatch', () => {
	const ctx = 'CT chest|cough';
	it('calls once per new normalised text, not again for whitespace or case changes', () => {
		const sent = new Set<string>();
		const first = planMatch(sent, ctx, null, [f(1, 'A 6 mm solid nodule.')], true);
		expect(first).toMatchObject({ call: true, reason: 'new_text' });
		markSent(sent, first.findings);
		expect(planMatch(sent, ctx, ctx, [f(1, '  a 6 MM  solid nodule ')], true)).toMatchObject({ call: false, reason: 'none' });
		const third = planMatch(sent, ctx, ctx, [f(1, 'A 6 mm solid nodule.'), f(2, 'A 2 cm cyst.')], true);
		expect(third).toMatchObject({ call: true, reason: 'new_text' });
		expect(third.findings.map((x) => x.id)).toEqual(['u1', 'u2']); // always all stable findings
	});
	it('a context change resets the plan', () => {
		const sent = new Set([norm('A 6 mm solid nodule.')]);
		expect(planMatch(sent, 'CT chest|new history', ctx, [f(1, 'A 6 mm solid nodule.')], true)).toMatchObject({ call: true, reason: 'context' });
	});
	it('makes an empty-findings first call when text exists (exam cards)', () => {
		expect(planMatch(new Set(), ctx, null, [], true)).toEqual({ call: true, findings: [], reason: 'exam' });
		expect(planMatch(new Set(), ctx, ctx, [], true)).toMatchObject({ call: false });
		expect(planMatch(new Set(), ctx, null, [], false)).toMatchObject({ call: false, reason: 'none' });
	});
	it('sends at most 20 findings', () => {
		const many = Array.from({ length: 25 }, (_, i) => f(i + 1, `finding ${i}`));
		expect(planMatch(new Set(), ctx, null, many, true).findings).toHaveLength(20);
	});
});

describe('groupCards', () => {
	it('keeps findings with identical text but different ids as separate groups', () => {
		const findings = [f(1, 'A simple cyst.'), f(4, 'a simple cyst')];
		const c1 = card({ key: 'bosniak-2019', finding_id: 'u1', finding: 'A simple cyst.' });
		const c4 = card({ key: 'bosniak-2019', finding_id: 'u4', finding: 'a simple cyst' });
		const groups = groupCards([c1, c4, c1], findings);
		expect(groups.map((g) => [g.finding?.id, g.cards.length])).toEqual([
			['u1', 1],
			['u4', 1]
		]);
	});
	it('follows a renumbered unit by its text', () => {
		const groups = groupCards([card({ finding_id: 'u1', finding: 'A 6 mm solid nodule.' })], [f(3, 'A 6 mm solid nodule.')]);
		expect(groups[0].finding?.id).toBe('u3');
	});
	it('places a card with no finding text by its finding_id only', () => {
		const c = card({ finding_id: 'u2', finding: '' });
		expect(groupCards([c], [f(1, 'x'), f(2, 'y')])[0].finding?.id).toBe('u2');
		expect(groupCards([c], [f(1, 'x')])).toEqual([]);
	});
	it('keeps exam cards first, groups by finding in dictation order, drops cards of deleted findings', () => {
		const exam = card({ key: 'cad-rads-2022', finding_id: 'exam', finding: 'whole dictation' });
		const nodule = card({ finding_id: 'u7', finding: 'A 6 mm solid nodule.' });
		const cyst = card({ key: 'bosniak-2019', finding_id: 'u2', finding: 'A 2 cm cyst.' });
		const gone = card({ key: 'li-rads', finding_id: 'u9', finding: 'A deleted lesion.' });
		const findings = [f(1, 'a 6 mm solid nodule'), f(2, 'A 2 cm cyst.')];
		const groups = groupCards([cyst, gone, nodule, exam], findings);
		expect(groups.map((g) => [g.finding?.id ?? null, g.cards.map((c) => c.key)])).toEqual([
			[null, ['cad-rads-2022']],
			['u1', ['fleischner-2017']],
			['u2', ['bosniak-2019']]
		]);
	});
	it('omits the exam group when there are no exam cards', () => {
		expect(groupCards([card()], [f(1, 'A 6 mm solid nodule')])[0].finding?.id).toBe('u1');
	});
});

describe('cardRef', () => {
	it('survives unit renumbering', () => {
		expect(cardRef(card({ finding_id: 'u1' }))).toBe(cardRef(card({ finding_id: 'u4', finding: 'A 6 mm solid nodule.' })));
		expect(cardRef(card({ finding_id: 'exam', finding: 'x' }))).toBe('fleischner-2017|exam');
	});
});

describe('kindOf', () => {
	it.each([
		['needs_modality', card({ needs_modality: 'US', reference: true, key: 'tnm-x' }), false],
		['reference', card({ reference: true, key: 'tnm-x' }), false],
		['tnm', card({ key: 'tnm-lung-9', finding_id: 'exam' }), false],
		['exam', card({ finding_id: 'exam' }), true],
		['other', card(), true],
		['finding', card(), false]
	])('%s', (kind, c, fromOther) => {
		expect(kindOf(c as Card, fromOther as boolean)).toBe(kind);
	});
});

describe('outcomeOf', () => {
	it('prefers draft_outcome over the proposal', () => {
		expect(outcomeOf(preview({ draft_outcome: prop('Bosniak II') }))?.classification).toBe('Bosniak II');
		expect(outcomeOf(preview())?.classification).toBe('CAD-RADS 0');
		expect(outcomeOf(null)).toBeNull();
	});
});

describe('groupCards: long findings', () => {
	it('a finding over 1000 characters is placed by the text /match was sent (cut to 1000)', () => {
		const long = 'nodule '.repeat(200); // 1400 characters
		const c = card({ finding: long.slice(0, 1000), finding_id: 'u1' });
		const groups = groupCards([c], [f(1, long)]);
		expect(groups).toHaveLength(1);
		expect(groups[0].cards).toEqual([c]);
	});
});

const draft = (o: Partial<DraftValue> = {}): DraftValue => ({
	input: 'a', label: '', role: '', scope: '', fact: '', state: 'read', value: '1', quote: '', why: [], needed: false, waiting: false, options: [], ...o
});
describe('quiet', () => {
	const exam = card({ finding_id: 'exam' });
	it('is true for a settled exam card', () => {
		expect(quiet(exam, preview())).toBe(true);
	});
	it.each([
		['a draft value is pre-filled', preview({ draft: [draft({ state: 'prefilled' })] })],
		['missing is non-empty', preview({ missing: ['stenosis'] })],
		['degraded', preview({ degraded: true })],
		['state is not applies', preview({ state: 'check_first' })],
		['there is no outcome', preview({ proposal: null })]
	])('is false when %s', (_why, p) => {
		expect(quiet(exam, p)).toBe(false);
	});
	it('stays quiet when the only preset values were set by the exam', () => {
		expect(quiet(exam, preview({ settled: [{ input: 'age', value: '60', quote: '', fact: 'age', by: 'exam' }] }))).toBe(true);
		expect(quiet(exam, preview({ draft: [draft({ state: 'prefilled', by: 'exam' })] }))).toBe(true);
		expect(quiet(exam, preview({ draft: [draft({ state: 'read' })] }))).toBe(true);
	});
	it('prefers Proposal.normal when the backend sends it', () => {
		expect(quiet(exam, preview({ proposal: { ...prop('CAD-RADS 0'), normal: true } }))).toBe(true);
		expect(quiet(exam, preview({ proposal: { ...prop('CAD-RADS 3'), normal: false } }))).toBe(false);
		expect(quiet(exam, preview({ proposal: { ...prop('CAD-RADS 0'), normal: true }, missing: ['x'] }))).toBe(false);
	});
	it('is false for a finding card or no preview', () => {
		expect(quiet(card(), preview())).toBe(false);
		expect(quiet(exam, null)).toBe(false);
	});
});
