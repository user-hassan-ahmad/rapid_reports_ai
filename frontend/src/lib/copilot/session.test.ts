// The Copilot session store (Task A6). SYNTHETIC rounds, a fake api with hand-resolved promises, fake timers.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { StackUnit } from '$lib/hybrid-stack/types';
import { CopilotError, CopilotOff } from './api';
import { assumption, card, draft, outcome, preview, result } from './cards/fixtures';
import { CONCLUSION_DEBOUNCE_MS, CONTEXT_DEBOUNCE_MS, createCopilotSession, EXAM_REOPEN_MS, MATCH_BACKOFF_MS, type CopilotApi } from './session';
import { cardRef } from './state';
import { CHANGED } from './applied';
import { unresolved } from './gate';
import { findingsText } from '$lib/hybrid-stack/regionState';
import type { CalculateBody, CalculateResult, Card, Calculation, ConclusionCheckBody, ConclusionCheckResult, MatchBody, MatchResult, OpenBody, OpenResult } from './types';

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
const G = ['Lungs']; // the schema groups the scratchpad hands each round (P2c: units + groups, no findings text)
/** Units whose text changes the findings text without changing the abnormal findings (exam re-open cases). */
const words = (...ws: string[]) => [unit(1, A), ...ws.map((w, i) => unit(10 + i, w, { abnormal: false }))];

type Call<B, R> = { body: B; resolve: (r: R) => void; reject: (e: unknown) => void };
function fakeApi() {
	const calls = {
		match: [] as Call<MatchBody, MatchResult>[],
		other: [] as Call<MatchBody, MatchResult>[],
		open: [] as Call<OpenBody, OpenResult>[],
		preview: [] as Call<OpenBody, OpenResult>[],
		calculate: [] as Call<CalculateBody, CalculateResult>[],
		conclusion: [] as Call<ConclusionCheckBody, ConclusionCheckResult>[]
	};
	const pending =
		<B, R>(list: Call<B, R>[]) =>
		(body: B) =>
			new Promise<R>((resolve, reject) => list.push({ body, resolve, reject }));
	const api: CopilotApi = {
		match: pending(calls.match),
		matchOther: pending(calls.other),
		open: pending(calls.open),
		preview: pending(calls.preview),
		calculate: pending(calls.calculate),
		conclusionCheck: pending(calls.conclusion)
	};
	return { api, calls };
}
const flush = () => vi.advanceTimersByTimeAsync(0);
const matched = (cards: Card[]): MatchResult => ({ cards, ms: 5 });

const A = 'a 6 mm solid nodule';
const B = 'a 2 cm cyst';
const nodule = card({ finding_id: 'u1', finding: A });

let api: ReturnType<typeof fakeApi>;
let s: ReturnType<typeof createCopilotSession>;
beforeEach(() => {
	vi.useFakeTimers();
	api = fakeApi();
	s = createCopilotSession(api.api);
	s.setContext({ scanType: 'CT chest', history: 'cough' });
});
afterEach(() => {
	s.destroy();
	vi.useRealTimers();
});
const state = () => get(s.state);

/** Round 1 places u1 still growing (no stable finding: the call carries only the dictation, for exam cards);
 *  round 2 repeats it, so it is stable and matched. Resolves both with `cards`. */
async function matchA(cards: Card[] = [nodule]) {
	const us = [unit(1, A)];
	s.round(us, true, G);
	api.calls.match[0].resolve(matched([]));
	await flush();
	s.round(us, true, G);
	api.calls.match[1].resolve(matched(cards));
	await flush();
}

describe('session: matching', () => {
	it('a growing last unit makes no call for it until it is stable', async () => {
		s.round([unit(1, 'a 6 mm')], true, G);
		expect(api.calls.match).toHaveLength(1);
		expect(api.calls.match[0].body.findings).toEqual([]); // exam-only first call
		api.calls.match[0].resolve(matched([]));
		await flush();
		s.round([unit(1, 'a 6 mm solid')], true, G);
		s.round([unit(1, A)], true, G);
		expect(api.calls.match).toHaveLength(1);
		s.round([unit(1, A)], true, G);
		expect(api.calls.match).toHaveLength(2);
		expect(api.calls.match[1].body.findings).toEqual([{ id: 'u1', text: A }]);
	});

	it('a stopped recording makes the last finding stable at once (Q4)', () => {
		s.round([unit(1, A)], false, G);
		expect(api.calls.match[0].body.findings).toEqual([{ id: 'u1', text: A }]);
	});

	it('a second identical round makes no call', async () => {
		await matchA();
		s.round([unit(1, A)], true, G);
		s.round([unit(1, A)], false, G);
		await flush();
		expect(api.calls.match).toHaveLength(2);
		expect(state().groups[0].cards).toEqual([nodule]);
	});

	it('a new finding calls once, carrying all stable findings', async () => {
		await matchA();
		const us = [unit(1, A), unit(2, B, { group: 'Kidneys' })];
		s.round(us, true, G); // u2 still growing, u1 already sent
		expect(api.calls.match).toHaveLength(2);
		s.round(us, true, G);
		expect(api.calls.match).toHaveLength(3);
		expect(api.calls.match[2].body.findings.map((f) => f.text)).toEqual([A, B]);
	});

	it('an edit to a finding drops its cards and later matches the new text', async () => {
		await matchA();
		expect(state().groups).toHaveLength(1);
		s.round([unit(1, 'a 9 mm solid nodule')], false, G);
		expect(state().groups).toEqual([]);
		expect(api.calls.match).toHaveLength(3);
		expect(api.calls.match[2].body.findings).toEqual([{ id: 'u1', text: 'a 9 mm solid nodule' }]);
	});

	it('reopening an open, loading or loaded card does not republish (final review C-1)', async () => {
		await matchA();
		s.open(cardRef(nodule));
		let n = 0;
		const stop = s.state.subscribe(() => n++);
		n = 0;                                   // subscribe calls back once at once
		s.open(cardRef(nodule));
		s.open(cardRef(nodule));
		expect(n).toBe(0);
		stop();
	});

	it('reopening a card whose result has landed neither republishes nor fetches again (final review C-1)', async () => {
		await matchA();
		s.open(cardRef(nodule));
		for (const c of [...api.calls.open, ...api.calls.preview]) c.resolve(result(nodule, preview()));
		await flush();
		const view = state().views[cardRef(nodule)];
		expect(view.loading).toBe(false);
		expect(view.result).not.toBeNull();
		const fetched = api.calls.open.length + api.calls.preview.length;
		let n = 0;
		const stop = s.state.subscribe(() => n++);
		n = 0;
		s.open(cardRef(nodule));
		s.open(cardRef(nodule));
		expect(n).toBe(0);
		expect(api.calls.open.length + api.calls.preview.length).toBe(fetched);
		stop();
	});

	it('a context change resets the cards, views and sent cache, and matches again', async () => {
		await matchA();
		s.open(cardRef(nodule));
		expect(Object.keys(state().views)).toHaveLength(1);
		s.setContext({ scanType: 'CT chest', history: 'weight los' });
		s.setContext({ scanType: 'CT chest', history: 'weight loss' }); // keystrokes: debounced, one reset
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS - 10);
		expect(state().groups).toHaveLength(1);
		expect(api.calls.match).toHaveLength(2);
		await vi.advanceTimersByTimeAsync(20);
		expect(state().groups).toEqual([]);
		expect(state().views).toEqual({});
		expect(api.calls.match).toHaveLength(3);
		expect(api.calls.match[2].body).toMatchObject({ clinical_history: 'weight loss', findings: [{ id: 'u1', text: A }] });
		s.setContext({ scanType: 'CT chest', history: 'weight loss' }); // unchanged: nothing
		expect(api.calls.match).toHaveLength(3);
	});

	it('a stale response is dropped', async () => {
		s.round([unit(1, A)], false, G);
		s.setContext({ scanType: 'CT abdomen', history: '' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		expect(api.calls.match).toHaveLength(2);
		api.calls.match[0].resolve(matched([card({ key: 'stale-pack', finding: A })]));
		await flush();
		expect(state().groups).toEqual([]);
		api.calls.match[1].resolve(matched([nodule]));
		await flush();
		expect(state().groups[0].cards.map((c) => c.key)).toEqual([nodule.key]);
	});

	it('one /match in flight at a time; plans made during it queue one follow-up', async () => {
		s.round([unit(1, A)], false, G);
		const us2 = [unit(1, A), unit(2, B)];
		s.round(us2, false, G);
		const us3 = [...us2, unit(3, 'a 1 cm lymph node')];
		s.round(us3, false, G);
		expect(api.calls.match).toHaveLength(1);
		expect(state().matching).toBe(true);
		api.calls.match[0].resolve(matched([nodule]));
		await flush();
		expect(api.calls.match).toHaveLength(2);
		expect(api.calls.match[1].body.findings.map((f) => f.id)).toEqual(['u1', 'u2', 'u3']);
		expect(api.calls.match[1].body.units).toEqual(us3); // the server builds the findings text (one builder)
		expect(api.calls.match[1].body.groups).toEqual(G);
		expect(api.calls.match[1].body).not.toHaveProperty('dictation');
	});

	it('a /match failure leaves no cards, sets matchFailed and caches nothing; retryMatch calls again', async () => {
		s.round([unit(1, A)], false, G);
		api.calls.match[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state()).toMatchObject({ matchFailed: true, matching: false, groups: [] });
		s.round([unit(1, A), unit(2, B)], false, G); // backing off: no call per round
		expect(api.calls.match).toHaveLength(1);
		s.retryMatch(); // Retry bypasses the backoff
		expect(api.calls.match).toHaveLength(2);
		expect(state().matchFailed).toBe(false);
		api.calls.match[1].resolve(matched([nodule]));
		await flush();
		expect(state().groups).toHaveLength(1);
		expect(s.log().failed).toEqual({ match: 1 });
	});

	it('after a failed /match, rounds resume calling once the backoff has passed', async () => {
		s.round([unit(1, A)], false, G);
		api.calls.match[0].reject(new CopilotError('network'));
		await flush();
		s.round([unit(1, A)], false, G);
		expect(api.calls.match).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(MATCH_BACKOFF_MS);
		s.round([unit(1, A)], false, G);
		expect(api.calls.match).toHaveLength(2);
	});

	it('a context change bypasses the failed-match backoff', async () => {
		await matchA();
		s.round([unit(1, A), unit(2, B)], false, G);
		api.calls.match[2].reject(new CopilotError('network'));
		await flush();
		s.setContext({ scanType: 'CT chest', history: 'new history' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		expect(api.calls.match).toHaveLength(4);
		expect(api.calls.match[3].body.clinical_history).toBe('new history');
	});

	it('a context typed back to its old value cancels the pending reset', async () => {
		await matchA();
		s.setContext({ scanType: 'CT chest', history: 'coughs' });
		s.setContext({ scanType: 'CT chest', history: 'cough' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS * 2);
		expect(state().groups).toHaveLength(1);
		expect(api.calls.match).toHaveLength(2);
	});

	it('a CopilotOff (404) turns the session off and later calls are never made', async () => {
		s.round([unit(1, A)], false, G);
		api.calls.match[0].reject(new CopilotOff());
		await flush();
		expect(state().on).toBe(false);
		s.round([unit(1, A), unit(2, B)], false, G);
		s.setContext({ scanType: 'MRI', history: '' });
		s.open(cardRef(nodule));
		s.other();
		s.retryMatch();
		expect(api.calls.match).toHaveLength(1);
		expect(api.calls.open).toHaveLength(0);
		expect(api.calls.other).toHaveLength(0);
	});

	it('a CopilotOff from /open turns it off too', async () => {
		await matchA();
		s.open(cardRef(nodule));
		api.calls.open[0].reject(new CopilotOff());
		await flush();
		expect(state()).toMatchObject({ on: false, groups: [] });
	});
});

describe('session: opening cards', () => {
	const exam = card({ key: 'cad-rads-2', name: 'CAD-RADS 2.0', finding_id: 'exam', finding: 'whole dictation' });

	it('exam cards auto-open with finding = findingsText, and /match and /open carry the same units and groups', async () => {
		s.round([unit(1, A)], false, G);
		api.calls.match[0].resolve(matched([exam, nodule]));
		await flush();
		// both previewed in the background (checkpoint 4: the verdict upfront); neither is opened
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual([exam.key, nodule.key]);
		expect(state().views[cardRef(nodule)]).toMatchObject({ open: false, loading: true });
		const body = api.calls.open[0].body;
		expect(body.card).toEqual(exam);
		expect(body.finding).toBe(findingsText([unit(1, A)], G));
		expect(body.units).toEqual(api.calls.match[0].body.units);
		expect(body.groups).toEqual(G);
		expect(body).not.toHaveProperty('findings');
		expect(state().views[cardRef(exam)]).toMatchObject({ open: false, loading: true });
		api.calls.open[0].resolve(result(exam, preview()));
		await flush();
		expect(state().views[cardRef(exam)].result?.preview?.state).toBe('applies');
		expect(s.log().quiet).toEqual(['cad-rads-2']);
	});

	it('exam cards re-open, debounced, when recording stops and the findings text changed', async () => {
		s.round(words('one'), false, G);
		api.calls.match[0].resolve(matched([exam]));
		await flush();
		api.calls.open[0].resolve(result(exam, preview()));
		await flush();
		s.round(words('one', 'two'), true, G); // recording: no re-open
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS * 2);
		expect(api.calls.open).toHaveLength(1);
		s.round(words('one', 'two', 'three'), false, G);
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS - 10);
		expect(api.calls.open).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(20);
		expect(api.calls.open).toHaveLength(2);
		expect(api.calls.open[1].body.finding).toBe(findingsText(words('one', 'two', 'three'), G));
		api.calls.open[1].resolve(result(exam, preview()));
		await flush();
		s.round(words('one', 'two', 'three'), false, G); // unchanged text: no re-open
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS * 2);
		expect(api.calls.open).toHaveLength(2);
	});

	it('open: the body uses the finding text; a reopen with a result sends nothing; close keeps the result', async () => {
		await matchA();
		const ref = cardRef(nodule);
		s.open(ref);
		expect(api.calls.open[0].body).toEqual({ card: nodule, finding: A, units: [unit(1, A)], groups: G, clinical_history: 'cough', answered: {}, patient: {} });
		api.calls.open[0].resolve(result(nodule, preview()));
		await flush();
		s.close(ref);
		expect(state().views[ref]).toMatchObject({ open: false });
		expect(state().views[ref].result).not.toBeNull();
		s.open(ref);
		expect(api.calls.open).toHaveLength(1);
		expect(s.log().opened).toEqual([nodule.key]);
	});

	it('a failed open shows the error on that card only; retry opens it again', async () => {
		await matchA();
		const ref = cardRef(nodule);
		s.open(ref);
		api.calls.open[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[ref]).toMatchObject({ loading: false, error: 'timeout' });
		expect(state().on).toBe(true);
		s.retry(ref);
		expect(api.calls.open).toHaveLength(2);
		expect(state().views[ref]).toMatchObject({ loading: true, error: null });
	});

	it('siblings open in parallel, one call per column, the card echoed with its key swapped', async () => {
		const sib = card({ finding_id: 'u1', finding: A, siblings: ['bts-pulmonary-nodule'], needs_modality: '' });
		await matchA([sib]);
		s.open(cardRef(sib));
		expect(api.calls.open).toHaveLength(2);
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual([sib.key, 'bts-pulmonary-nodule']);
		expect(api.calls.open[1].body.card).toEqual({ ...sib, key: 'bts-pulmonary-nodule', name: 'bts-pulmonary-nodule' });
		api.calls.open[1].resolve(result(card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' }), preview()));
		await flush();
		const cols = state().views[cardRef(sib)].columns!;
		expect(cols['bts-pulmonary-nodule'].result?.entry?.name).toBe('BTS 2015');
		expect(cols[sib.key].loading).toBe(true);
	});

	it('a column retry splits its ref on the LAST "#" and re-opens that column only', async () => {
		const hashText = 'nodule #2 in the right lung';
		const sib = card({ finding_id: 'u1', finding: hashText, siblings: ['bts-pulmonary-nodule'] });
		s.round([unit(1, hashText)], false, G);
		api.calls.match[0].resolve(matched([sib]));
		await flush();
		s.open(cardRef(sib));
		api.calls.open[1].reject(new CopilotError('network'));
		await flush();
		expect(state().views[cardRef(sib)].columns!['bts-pulmonary-nodule'].error).toBe('network');
		s.retry(`${cardRef(sib)}#bts-pulmonary-nodule`);
		expect(api.calls.open).toHaveLength(3);
		expect(api.calls.open[2].body.card.key).toBe('bts-pulmonary-nodule');
	});

	it('needs-modality cards never open: not on arrival, not on click, not on retry', async () => {
		const examUs = card({ key: 'bta-thyroid-u-grading', finding_id: 'exam', needs_modality: 'US' });
		const findUs = card({ key: 'bta-x', finding_id: 'u1', finding: A, needs_modality: 'US' });
		await matchA([examUs, findUs]);
		s.open(cardRef(examUs));
		s.open(cardRef(findUs));
		s.retry(cardRef(findUs));
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS * 2);
		expect(api.calls.open).toHaveLength(0);
	});

	it('other: merges /match/other cards without duplicates, each tagged fromOther', async () => {
		await matchA();
		const extra = card({ key: 'web-guide', name: 'A society guide', finding_id: 'u1', finding: A, known: false });
		s.other();
		expect(state().otherState).toBe('loading');
		expect(api.calls.other[0].body.findings).toEqual([{ id: 'u1', text: A }]);
		api.calls.other[0].resolve(matched([nodule, extra, extra]));
		await flush();
		expect(state().otherState).toBe('done');
		expect(state().groups[0].cards.map((c) => c.key)).toEqual([nodule.key, 'web-guide']);
		expect(state().views[cardRef(extra)].fromOther).toBe(true);
		expect(state().views[cardRef(nodule)]?.fromOther).toBeUndefined();
		// a later /match keeps the other card
		s.round([unit(1, A), unit(2, B)], false, G);
		api.calls.match[2].resolve(matched([nodule]));
		await flush();
		expect(state().groups[0].cards.map((c) => c.key)).toEqual([nodule.key, 'web-guide']);
	});

	it('other failure sets failed; destroy aborts in-flight calls and drops their answers', async () => {
		await matchA();
		s.other();
		api.calls.other[0].reject(new CopilotError('http', 500));
		await flush();
		expect(state().otherState).toBe('failed');
		s.open(cardRef(nodule));
		const before = state();
		s.destroy();
		api.calls.open[0].resolve(result(nodule, preview()));
		await flush();
		expect(get(s.state)).toEqual(before);
	});

	it('an exam card with siblings: open reuses the auto-opened primary and fetches only the sibling', async () => {
		const examSib = card({ key: 'cad-rads-2', finding_id: 'exam', finding: 'x', siblings: ['other-cta-pack'] });
		s.round([unit(1, A)], false, G);
		api.calls.match[0].resolve(matched([examSib]));
		await flush();
		// the primary auto-opens and the sibling column is previewed in the background
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['cad-rads-2', 'other-cta-pack']);
		s.open(cardRef(examSib)); // both still loading: nothing asked again
		expect(api.calls.open).toHaveLength(2);
	});

	it('a sibling card retry re-fetches only the failed columns', async () => {
		const sib = card({ finding_id: 'u1', finding: A, siblings: ['bts-pulmonary-nodule'] });
		await matchA([sib]);
		s.open(cardRef(sib));
		api.calls.open[0].resolve(result(sib, preview()));
		api.calls.open[1].reject(new CopilotError('timeout'));
		await flush();
		s.retry(cardRef(sib));
		expect(api.calls.open).toHaveLength(3);
		expect(api.calls.open[2].body.card.key).toBe('bts-pulmonary-nodule');
	});

	it('an /open answer from before a reset never lands on a later request of the same card', async () => {
		await matchA();
		s.open(cardRef(nodule));
		s.setContext({ scanType: 'CT chest', history: 'other' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		api.calls.match[2].resolve(matched([nodule]));
		await flush();
		s.open(cardRef(nodule));
		expect(api.calls.open).toHaveLength(2);
		api.calls.open[0].resolve(result(nodule, preview({ proposal: null, possible: ['old'] })));
		await flush();
		expect(state().views[cardRef(nodule)]).toMatchObject({ loading: true, result: null });
		api.calls.open[1].resolve(result(nodule, preview()));
		await flush();
		expect(state().views[cardRef(nodule)].result?.preview?.possible).toEqual([]);
	});

	it('a card first found by Other loses its "other" tag when /match later returns it', async () => {
		await matchA();
		const extra = card({ key: 'web-guide', finding_id: 'u1', finding: A });
		s.other();
		api.calls.other[0].resolve(matched([extra]));
		await flush();
		expect(state().views[cardRef(extra)].fromOther).toBe(true);
		s.round([unit(1, A), unit(2, B)], false, G);
		api.calls.match[2].resolve(matched([nodule, extra]));
		await flush();
		expect(state().views[cardRef(extra)].fromOther).toBe(false);
	});

	it('an exam re-open keeps the last result while it loads', async () => {
		s.round(words('one'), false, G);
		api.calls.match[0].resolve(matched([exam]));
		await flush();
		api.calls.open[0].resolve(result(exam, preview()));
		await flush();
		s.round(words('one', 'two'), false, G);
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS);
		expect(state().views[cardRef(exam)].loading).toBe(true);
		expect(state().views[cardRef(exam)].result).not.toBeNull();
	});

	it('log carries keys, counts and ms only: no finding text', async () => {
		await matchA();
		s.open(cardRef(nodule));
		api.calls.open[0].resolve(result(nodule, preview()));
		await flush();
		const l = s.log();
		expect(l.matched).toEqual([nodule.key]);
		expect(JSON.stringify(l)).not.toContain('nodule ');
		expect(JSON.stringify(l)).not.toContain(A);
	});
});

describe('session: edits, shared patient answers and Calculate (Slice B2)', () => {
	// SYNTHETIC: an adrenal-like card whose age carries the shared patient fact "age", and a second card with it too
	const adrenal = card({ key: 'ese-adrenal-incidentaloma', finding_id: 'u1', finding: A });
	const other = card({ key: 'other-pack', finding_id: 'u1', finding: A });
	const drafted = (c: Card, extra = {}) =>
		result(
			c,
			preview({
				proposal: null,
				draft_outcome: outcome({ classification: 'Benign', recommendation: 'No further imaging.' }),
				draft: [
					draft({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm' }),
					draft({ input: 'hu', label: 'HU', state: 'prefilled', value: '8 HU', why: ['x'] }),
					draft({ input: 'age', label: 'Age', scope: 'patient', fact: 'age', state: 'asked', needed: true }),
					draft({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No' }),
					draft({ input: 'later', label: 'Later', state: 'asked', waiting: true }),
					draft({ input: 'side', label: 'Side', state: 'not_applicable' })
				],
				...extra
			})
		);
	const calc = (o: Partial<Calculation> = {}): Calculation => ({
		outcome: 'benign', result: outcome({ classification: 'Benign' }), exclusion: null, possible: [], needed: [], values: [], assumptions: [assumption('cancer', 'Known cancer')], trace: null, pack: 'p@1', bundle: 'b', ...o
	});

	async function opened(cards: Card[] = [adrenal]) {
		await matchA(cards);
		for (const [i, c] of cards.entries()) {
			s.open(cardRef(c));
			api.calls.open[i].resolve(drafted(c));
		}
		await flush();
	}

	it('Calculate sends exactly the values shown (assumed included; asked, waiting and N/A never), with the card echoed', async () => {
		await opened();
		s.calculate(cardRef(adrenal));
		expect(api.calls.calculate).toHaveLength(1);
		const body = api.calls.calculate[0].body;
		expect(body.values).toEqual({ size: '2.2 cm', hu: '8 HU', cancer: 'No' });
		expect(body.card).toEqual(adrenal);
		expect(body.units).toEqual([unit(1, A)]);
		expect(body.groups).toEqual(G);
		expect(state().views[cardRef(adrenal)].calc).toMatchObject({ loading: true });
		api.calls.calculate[0].resolve({ calculation: calc(), ms: 4, error: null });
		await flush();
		expect(state().views[cardRef(adrenal)].calc).toMatchObject({ loading: false, error: null, result: { assumptions: [{ input: 'cancer' }] } });
	});

	it('an edit goes to `answered`, re-previews the card, and is included in the values; "Not stated" is sent as NOT_STATED', async () => {
		await opened();
		s.edit(cardRef(adrenal), 'hu', '12 HU');
		expect(api.calls.preview).toHaveLength(1);
		expect(api.calls.preview[0].body.answered).toEqual({ hu: '12 HU' });
		s.edit(cardRef(adrenal), 'size', 'Not stated');
		expect(api.calls.preview[1].body.answered).toEqual({ hu: '12 HU', size: 'Not stated' });
		api.calls.preview[1].resolve(drafted(adrenal));
		await flush();
		s.calculate(cardRef(adrenal));
		expect(api.calls.calculate[0].body.values).toEqual({ size: 'Not stated', hu: '12 HU', cancer: 'No' });
		expect(api.calls.calculate[0].body.answered).toEqual({ hu: '12 HU', size: 'Not stated' });
	});

	it('an edit after Calculate clears the result, and a Calculate still in flight is dropped', async () => {
		await opened();
		s.calculate(cardRef(adrenal));
		api.calls.calculate[0].resolve({ calculation: calc(), ms: 4, error: null });
		await flush();
		expect(state().views[cardRef(adrenal)].calc?.result).not.toBeNull();
		s.edit(cardRef(adrenal), 'hu', '9 HU');
		expect(state().views[cardRef(adrenal)].calc).toBeUndefined();
		api.calls.preview[0].resolve(drafted(adrenal));
		await flush();
		s.calculate(cardRef(adrenal));
		s.edit(cardRef(adrenal), 'hu', '10 HU');
		api.calls.calculate[1].resolve({ calculation: calc(), ms: 4, error: null });
		await flush();
		expect(state().views[cardRef(adrenal)].calc).toBeUndefined();
	});

	it('a patient answer goes into the case patient map and re-previews every other card with that fact', async () => {
		await opened([adrenal, other]);
		s.edit(cardRef(adrenal), 'age', '45');
		expect(api.calls.preview.map((c) => c.body.card.key)).toEqual([adrenal.key, other.key]);
		expect(api.calls.preview[1].body.patient).toEqual({ age: '45' });
		expect(api.calls.preview[1].body.answered).toEqual({}); // the other card's own answers are untouched
		api.calls.preview[1].resolve(drafted(other));
		await flush();
		// later requests carry the patient map too
		s.calculate(cardRef(other));
		expect(api.calls.calculate[0].body.patient).toEqual({ age: '45' });
	});

	it('N/A rows and needs-modality cards are not editable; a calculate error shows on the card', async () => {
		await opened();
		s.edit(cardRef(adrenal), 'side', 'Left');
		expect(api.calls.preview).toHaveLength(0);
		s.calculate(cardRef(adrenal));
		api.calls.calculate[0].resolve({ calculation: null, ms: 1, error: 'not a pack' });
		await flush();
		expect(state().views[cardRef(adrenal)].calc).toMatchObject({ error: 'not a pack', result: null });
		s.calculate(cardRef(adrenal));
		api.calls.calculate[1].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(adrenal)].calc).toMatchObject({ error: 'timeout' });
	});

	it('Calculate waits while the card re-previews after an edit (it would send stale values)', async () => {
		await opened();
		s.edit(cardRef(adrenal), 'hu', '12 HU');
		expect(state().views[cardRef(adrenal)].loading).toBe(true);
		s.calculate(cardRef(adrenal));
		expect(api.calls.calculate).toHaveLength(0);
		api.calls.preview[0].resolve(drafted(adrenal));
		await flush();
		s.calculate(cardRef(adrenal));
		expect(api.calls.calculate).toHaveLength(1);
	});

	it('a failed re-preview reverts the edit and says so; the last preview stays', async () => {
		await opened();
		s.edit(cardRef(adrenal), 'hu', '12 HU');
		api.calls.preview[0].reject(new CopilotError('timeout'));
		await flush();
		const v = state().views[cardRef(adrenal)];
		expect(v.edits).toEqual({});
		expect(v.editError).toContain('undone');
		expect(v.result?.preview?.draft?.length).toBeGreaterThan(0);
		expect(v.error).toBeNull();
	});

	it('a context change resets the shared patient answers', async () => {
		await opened();
		s.edit(cardRef(adrenal), 'age', '45');
		s.setContext({ scanType: 'CT chest', history: 'new' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		expect(api.calls.match.at(-1)!.body.patient).toEqual({});
	});

	it('sibling columns: each answers and calculates on its own; a patient answer reaches every column', async () => {
		const sib = card({ finding_id: 'u1', finding: A, siblings: ['bts-pulmonary-nodule'] });
		await matchA([sib]);
		s.open(cardRef(sib));
		api.calls.open[0].resolve(drafted(sib));
		api.calls.open[1].resolve(drafted(card({ key: 'bts-pulmonary-nodule', finding: A })));
		await flush();
		const col = `${cardRef(sib)}#bts-pulmonary-nodule`;
		s.edit(col, 'hu', '20 HU');
		expect(api.calls.preview).toHaveLength(1);
		expect(api.calls.preview[0].body.card.key).toBe('bts-pulmonary-nodule');
		expect(api.calls.preview[0].body.answered).toEqual({ hu: '20 HU' });
		expect(state().views[cardRef(sib)].columns!['bts-pulmonary-nodule'].edits).toEqual({ hu: '20 HU' });
		expect(state().views[cardRef(sib)].columns![sib.key].edits).toBeUndefined(); // the other column is untouched
		api.calls.preview[0].resolve(drafted(card({ key: 'bts-pulmonary-nodule', finding: A })));
		await flush();
		s.calculate(col);
		expect(api.calls.calculate[0].body.card.key).toBe('bts-pulmonary-nodule');
		expect(api.calls.calculate[0].body.values.hu).toBe('20 HU');
		api.calls.calculate[0].resolve({ calculation: calc(), ms: 3, error: null });
		await flush();
		expect(state().views[cardRef(sib)].columns!['bts-pulmonary-nodule'].calc?.result).not.toBeNull();
		expect(state().views[cardRef(sib)].columns![sib.key].calc).toBeUndefined();
		// a patient answer in the primary column re-previews the sibling column too
		s.edit(`${cardRef(sib)}#${sib.key}`, 'age', '60');
		expect(api.calls.preview.slice(1).map((c) => c.body.card.key)).toEqual([sib.key, 'bts-pulmonary-nodule']);
		expect(api.calls.preview[2].body.patient).toEqual({ age: '60' });
		expect(state().views[cardRef(sib)].columns!['bts-pulmonary-nodule'].calc).toBeUndefined(); // its result cleared
	});

	it('a reverted patient answer rolls back the shared fact and re-previews the cards that received it', async () => {
		await opened([adrenal, other]);
		s.edit(cardRef(adrenal), 'age', '45');
		expect(api.calls.preview.map((c) => [c.body.card.key, c.body.patient])).toEqual([
			[adrenal.key, { age: '45' }],
			[other.key, { age: '45' }]
		]);
		api.calls.preview[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(adrenal)].edits).toEqual({});
		// the other card is asked again without the answer that never took
		expect(api.calls.preview).toHaveLength(3);
		expect(api.calls.preview[2].body.card.key).toBe(other.key);
		expect(api.calls.preview[2].body.patient).toEqual({});
		s.calculate(cardRef(adrenal));
		expect(api.calls.calculate[0].body.patient).toEqual({});
	});

	it('a confirmed patient answer is what a later failed one rolls back to', async () => {
		await opened([adrenal, other]);
		s.edit(cardRef(adrenal), 'age', '45');
		api.calls.preview[0].resolve(drafted(adrenal));
		api.calls.preview[1].resolve(drafted(other));
		await flush();
		s.edit(cardRef(adrenal), 'age', '50');
		api.calls.preview[2].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(adrenal)].edits).toEqual({ age: '45' });
		expect(api.calls.preview.at(-1)!.body.patient).toEqual({ age: '45' });
	});

	it('a second edit during an in-flight re-preview reverts to the last previewed answers, not the unconfirmed first edit', async () => {
		await opened();
		s.edit(cardRef(adrenal), 'hu', '12 HU');
		s.edit(cardRef(adrenal), 'size', '3 cm');
		expect(api.calls.preview[1].body.answered).toEqual({ hu: '12 HU', size: '3 cm' });
		api.calls.preview[0].resolve(drafted(adrenal)); // superseded: dropped
		api.calls.preview[1].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(adrenal)].edits).toEqual({});
		// once an edit has been previewed, a later failure keeps it
		s.edit(cardRef(adrenal), 'hu', '12 HU');
		api.calls.preview[2].resolve(drafted(adrenal));
		await flush();
		s.edit(cardRef(adrenal), 'size', '3 cm');
		api.calls.preview[3].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(adrenal)].edits).toEqual({ hu: '12 HU' });
	});

});

describe('session: background previews (checkpoint 4)', () => {
	const pack = (key: string, extra: Partial<Card> = {}) => card({ key, finding_id: 'u1', finding: A, ...extra });

	it('every pack card is previewed after /match, at most MAX_PREFETCH at a time; read-only cards never', async () => {
		const packs = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6'].map((k) => pack(k));
		const ro = [pack('tnm-lung'), pack('bta-x', { needs_modality: 'US' }), pack('fazekas', { reference: true })];
		await matchA([...packs, ...ro]);
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['p1', 'p2', 'p3', 'p4']);
		api.calls.open[0].resolve(result(packs[0], preview()));
		await flush();
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['p1', 'p2', 'p3', 'p4', 'p5']);
		for (const c of api.calls.open.slice(1)) c.resolve(result(packs[1], preview()));
		await flush();
		api.calls.open.at(-1)!.resolve(result(packs[5], preview()));
		await flush();
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['p1', 'p2', 'p3', 'p4', 'p5', 'p6']);
		expect(state().views[cardRef(packs[0])]).toMatchObject({ open: false, loading: false });
		expect(state().views[cardRef(packs[0])].result).not.toBeNull();
	});

	it('a background preview that fails is silent (the card opens on click); one the radiologist opened shows its error', async () => {
		const a = pack('p1');
		const b = pack('p2');
		await matchA([a, b]);
		api.calls.open[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(a)]).toMatchObject({ loading: false, error: null, result: null });
		s.open(cardRef(a)); // nothing there: asks again, in the foreground
		expect(api.calls.open).toHaveLength(3);
		s.open(cardRef(b)); // already in flight: not asked again, but its failure now shows
		api.calls.open[1].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[cardRef(b)].error).toBe('timeout');
	});

	it('sibling columns are previewed too', async () => {
		const sib = pack('fleischner-pulmonary-nodule', { siblings: ['bts-pulmonary-nodule'] });
		await matchA([sib]);
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['fleischner-pulmonary-nodule', 'bts-pulmonary-nodule']);
		expect(state().views[cardRef(sib)]?.open ?? false).toBe(false);
	});

	it('queued background previews for cards a later /match removed are dropped', async () => {
		const packs = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6'].map((k) => pack(k));
		await matchA(packs);
		expect(api.calls.open).toHaveLength(4); // p5, p6 queued
		s.round([unit(1, A), unit(2, B)], false, G);
		api.calls.match[2].resolve(matched(packs.slice(0, 4))); // p5, p6 gone
		await flush();
		for (const c of api.calls.open) c.resolve(result(packs[0], preview()));
		await flush();
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['p1', 'p2', 'p3', 'p4']);
	});

	it('a failed background preview is not retried on every /match; it is on open, or after the backoff', async () => {
		const a = pack('p1');
		await matchA([a]);
		api.calls.open[0].reject(new CopilotError('timeout'));
		await flush();
		s.round([unit(1, A), unit(2, B)], false, G);
		api.calls.match[2].resolve(matched([a]));
		await flush();
		expect(api.calls.open).toHaveLength(1); // not retried by the next /match
		await vi.advanceTimersByTimeAsync(MATCH_BACKOFF_MS);
		s.round([unit(1, A), unit(2, B), unit(3, 'a 1 cm lymph node')], false, G);
		api.calls.match[3].resolve(matched([a]));
		await flush();
		expect(api.calls.open).toHaveLength(2); // after the backoff it is
		api.calls.open[1].reject(new CopilotError('timeout'));
		await flush();
		s.open(cardRef(a)); // a click always asks
		expect(api.calls.open).toHaveLength(3);
	});

	it('"Other guidelines" sends nothing while nothing is dictated', () => {
		s.other();
		expect(api.calls.other).toHaveLength(0);
		expect(state().otherState).toBe('idle');
	});
});

// Spec §7.12 item 5: the conclusion check behind the confirm gate, and "Seen, leave as is". SYNTHETIC.
describe('session: confirm gate', () => {
	const cyst = card({ key: 'cyst-pack', name: 'Cyst pack', finding_id: 'u2', finding: B });
	const workup = preview({ proposal: outcome({ headline: 'Consider PET-CT', action: 'PET-CT', category: 'workup' }) });
	const fine = preview({ proposal: outcome({ headline: 'Benign', action: 'No further imaging', category: 'none' }) });
	/** Two findings matched (nodule on A, cyst on B); their background previews land: the nodule needs work-up. */
	async function twoCards() {
		const us = [unit(1, A), unit(2, B)];
		s.round(us, true, G);
		api.calls.match[0].resolve(matched([]));
		await flush();
		s.round(us, true, G);
		api.calls.match[1].resolve(matched([nodule, cyst]));
		await flush();
		for (const c of api.calls.open) c.resolve(result(c.body.card, c.body.card.key === nodule.key ? workup : fine));
		await flush();
	}

	it('checkConclusion debounces, sends only significant cards, stores the categories', async () => {
		await twoCards();
		s.checkConclusion('Recommend');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS / 2);
		s.checkConclusion('Recommend PET-CT.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS - 1);
		expect(api.calls.conclusion).toHaveLength(0);
		await vi.advanceTimersByTimeAsync(1);
		expect(api.calls.conclusion).toHaveLength(1);
		const body = api.calls.conclusion[0].body;
		expect(body.conclusion).toBe('Recommend PET-CT.');
		expect(body.cards).toEqual([{ key: 'f0', finding: A }]); // the cyst card's verdict is not significant
		api.calls.conclusion[0].resolve({ results: { f0: 'workup' } });
		await flush();
		expect(state().concl).toEqual({ [cardRef(nodule)]: 'workup' });
		s.checkConclusion('Recommend PET-CT.'); // unchanged: no new call
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion).toHaveLength(1);
	});

	it('a rejected check stores null for those cards and does not throw', async () => {
		await twoCards();
		s.checkConclusion('Recommend PET-CT.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		api.calls.conclusion[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state().concl).toEqual({ [cardRef(nodule)]: null });
		expect(state().on).toBe(true);
	});

	it('an empty conclusion makes no call and clears nothing', async () => {
		await twoCards();
		s.checkConclusion('   ');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion).toHaveLength(0);
		expect(state().concl).toEqual({ [cardRef(nodule)]: null });
	});

	it('a card that turns significant after the check is checked under the same conclusion', async () => {
		const us = [unit(1, A)];
		s.round(us, true, G);
		api.calls.match[0].resolve(matched([]));
		await flush();
		s.round(us, true, G);
		api.calls.match[1].resolve(matched([nodule]));
		await flush();
		s.checkConclusion('Recommend PET-CT.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion).toHaveLength(0); // nothing significant yet: no call
		api.calls.open[0].resolve(result(nodule, workup));
		await flush();
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion).toHaveLength(1);
		expect(api.calls.conclusion[0].body.cards).toEqual([{ key: 'f0', finding: A }]);
	});

	it('seen(ref) holds the verdict it was tapped on; a new case context resets seen and the checks', async () => {
		await twoCards();
		s.seen(cardRef(nodule));
		expect(state().seen).toEqual({ [cardRef(nodule)]: 'workup|Consider PET-CT|' });
		s.setContext({ scanType: 'CT chest', history: 'weight loss' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		expect(state().seen).toEqual({});
		expect(state().concl).toEqual({});
	});

	// review I-1: an answer computed for another conclusion text never clears a card
	it('a text change empties concl at once; a late answer for the old text keeps it empty; the current one fills it', async () => {
		await twoCards();
		s.checkConclusion('Recommend PET-CT.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		api.calls.conclusion[0].resolve({ results: { f0: 'workup' } });
		await flush();
		expect(state().concl).toEqual({ [cardRef(nodule)]: 'workup' });
		expect(unresolved(state(), state().seen, state().concl)).toEqual([]);
		// edit with a check for the old text still in flight
		s.checkConclusion('Recommend PET-CT and biopsy.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion).toHaveLength(2);
		s.checkConclusion('Benign.');
		expect(state().concl).toEqual({}); // straight after the change, before the timer fires
		expect(unresolved(state(), state().seen, state().concl).map((u) => u.key)).toEqual([cardRef(nodule)]);
		api.calls.conclusion[1].resolve({ results: { f0: 'workup' } }); // late: for the old text
		await flush();
		expect(state().concl).toEqual({});
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion).toHaveLength(3);
		expect(api.calls.conclusion[2].body.conclusion).toBe('Benign.');
		api.calls.conclusion[2].resolve({ results: { f0: 'none' } });
		await flush();
		expect(state().concl).toEqual({ [cardRef(nodule)]: 'none' });
	});

	// review M-1: an exam card's answer is for the findings text it was sent with
	it('an exam card is checked again when the findings text changes under the same conclusion', async () => {
		const exam = card({ key: 'exam-pack', name: 'Exam pack', finding_id: 'exam', finding: 'one' });
		const us = [unit(1, 'one', { abnormal: false })];
		s.round(us, false, G);
		api.calls.match[0].resolve(matched([exam]));
		await flush();
		api.calls.open[0].resolve(result(exam, preview({ proposal: outcome({ headline: 'Consider PET-CT', category: 'workup', normal: false }) })));
		await flush();
		s.checkConclusion('Recommend PET-CT.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		expect(api.calls.conclusion[0].body.cards).toEqual([{ key: 'f0', finding: findingsText(us, G) }]);
		api.calls.conclusion[0].resolve({ results: { f0: 'workup' } });
		await flush();
		expect(state().concl).toEqual({ [cardRef(exam)]: 'workup' });
		const us2 = [unit(1, 'one two', { abnormal: false })];
		s.round(us2, false, G);
		expect(state().concl).toEqual({}); // the answer was for the old findings text
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		const last = api.calls.conclusion.at(-1)!;
		expect(last.body.cards).toEqual([{ key: 'f0', finding: findingsText(us2, G) }]);
	});

	// review M-5: at most ten findings go to the check; a card past the cap is answered null (its note says so)
	it('caps the findings sent at ten; cards past the cap get null', async () => {
		const texts = Array.from({ length: 11 }, (_, i) => `finding number ${i}`);
		const us = texts.map((t, i) => unit(i + 1, t));
		const cards = texts.map((t, i) => card({ key: `pack-${i}`, name: `Pack ${i}`, finding_id: `u${i + 1}`, finding: t }));
		s.round(us, false, G);
		api.calls.match[0].resolve(matched(cards));
		await flush();
		while (api.calls.open.some((c) => !(c as { done?: boolean }).done)) {
			for (const c of api.calls.open) if (!(c as { done?: boolean }).done) ((c as { done?: boolean }).done = true), c.resolve(result(c.body.card, workup));
			await flush();
		}
		s.checkConclusion('Recommend PET-CT.');
		await vi.advanceTimersByTimeAsync(CONCLUSION_DEBOUNCE_MS);
		const sent = api.calls.conclusion[0].body.cards;
		expect(sent).toHaveLength(10);
		api.calls.conclusion[0].resolve({ results: Object.fromEntries(sent.map((c) => [c.key, 'workup' as const])) });
		await flush();
		expect(Object.values(state().concl).filter((c) => c === 'workup')).toHaveLength(10);
		expect(state().concl[cardRef(cards[10])]).toBeNull();
	});
});

describe('session: ticks, pick and Apply (questionnaire card, spec 2026-10-14)', () => {
	const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015', finding_id: 'u1', finding: A });
	const ref = cardRef(bts);
	const rows = (kind = 'solid', size = '7 mm') => [
		draft({ input: 'size', label: 'Size', state: 'read', value: size, quote: size }),
		draft({ input: 'kind', label: 'Type', state: 'prefilled', value: kind, decisive: true, options: ['solid', 'subsolid', 'Not stated'] })
	];
	const ready = (over = {}) =>
		result(bts, preview({ proposal: null, draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.', headline: 'Solid nodule', action: 'CT at 3 months', category: 'surveillance' }), trace: { outcome: 'ct3' }, draft: rows(), ...over }));
	const calcOk = (o: Partial<Calculation> = {}): Calculation => ({
		outcome: 'ct3', result: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.' }), exclusion: null, possible: [], needed: [], assumptions: [], trace: null, pack: 'bts-pulmonary-nodule@2015', bundle: 'b7', values: rows(), ...o
	});
	async function openedBts(r = ready()) {
		await matchA([bts]);
		s.open(ref);
		api.calls.open[0].resolve(r);
		await flush();
	}
	async function applied() {
		s.tick(ref, 'kind', 'solid');
		s.apply(ref);
		api.calls.calculate.at(-1)!.resolve({ calculation: calcOk(), ms: 3, error: null });
		await flush();
	}

	it('Apply waits for the ✓ on a decisive pre-filled value, then writes one line from Calculate', async () => {
		await openedBts();
		s.apply(ref);
		expect(api.calls.calculate).toHaveLength(0); // not ready: Type is not confirmed
		s.tick(ref, 'kind', 'solid');
		s.apply(ref);
		expect(api.calls.calculate).toHaveLength(1);
		expect(api.calls.calculate[0].body.values).toEqual({ size: '7 mm', kind: 'solid' });
		api.calls.calculate[0].resolve({ calculation: calcOk(), ms: 3, error: null });
		await flush();
		expect(state().applied?.[ref]).toMatchObject({ key: ref, finding_id: 'u1', pack: 'bts-pulmonary-nodule', version: 'bts-pulmonary-nodule@2015', bundle: 'b7', source: 'BTS 2015', outcome: 'ct3', text: 'Solid nodule 6-8 mm: CT at 3 months (BTS 2015).' });
		expect(state().applied?.[ref].values.find((v) => v.input === 'kind')?.state).toBe('confirmed');
		expect(unresolved(state(), {}, {})).toEqual([]); // applied: the gate clears for this outcome
	});

	it('a re-read that changes a ticked value drops it', async () => {
		await openedBts();
		s.tick(ref, 'kind', 'solid');
		s.edit(ref, 'size', '9 mm');
		api.calls.preview[0].resolve(ready({ draft: rows('subsolid', '9 mm') }));
		await flush();
		s.apply(ref);
		expect(api.calls.calculate).toHaveLength(0);
	});

	it('a card re-previewed while Calculate runs writes nothing', async () => {
		await openedBts();
		s.tick(ref, 'kind', 'solid');
		s.apply(ref);
		s.edit(ref, 'size', '7 mm');
		api.calls.preview[0].resolve(ready());
		await flush();
		api.calls.calculate[0].resolve({ calculation: calcOk(), ms: 3, error: null });
		await flush();
		expect(state().applied?.[ref]).toBeUndefined();
		expect(state().views[ref].applyError).toBe(CHANGED);
	});

	it('a failed Calculate writes nothing and says so', async () => {
		await openedBts();
		s.tick(ref, 'kind', 'solid');
		s.apply(ref);
		api.calls.calculate[0].reject(new CopilotError('http', 500));
		await flush();
		expect(state().applied?.[ref]).toBeUndefined();
		expect(state().views[ref].applyError).toMatch(/^Couldn't apply/);
	});

	it('pick: with no question left, a complete candidate applies; chosen_from records N', async () => {
		const cands = [
			{ outcome: 'ct3', headline: 'CT at 3 months', category: 'surveillance' as const, proposal: outcome({ classification: 'BTS 2015 · Solid nodule', recommendation: 'CT at 3 months.' }) },
			{ outcome: 'pet', headline: 'PET-CT', category: 'workup' as const, proposal: null }
		];
		await openedBts(ready({ draft_outcome: null, trace: null, candidates: cands, draft: rows().slice(0, 1) }));
		s.apply(ref);
		s.pick(ref, 'pet');
		s.apply(ref);
		expect(api.calls.calculate).toHaveLength(0); // nothing picked, then an incomplete pick
		s.pick(ref, 'ct3');
		s.apply(ref);
		api.calls.calculate[0].resolve({ calculation: calcOk({ outcome: null, result: null, candidates: cands, values: rows().slice(0, 1) }), ms: 3, error: null });
		await flush();
		expect(state().applied?.[ref]).toMatchObject({ outcome: 'ct3', chosen_from: 2, text: 'Solid nodule: CT at 3 months (BTS 2015).' });
	});

	it('edit and remove change only that line; re-apply replaces it; a new case clears them', async () => {
		await openedBts();
		await applied();
		s.editApplied(ref, 'My wording.');
		expect(state().applied?.[ref].text).toBe('My wording.');
		await applied();
		expect(Object.keys(state().applied ?? {})).toEqual([ref]);
		expect(state().applied?.[ref].text).toBe('Solid nodule 6-8 mm: CT at 3 months (BTS 2015).');
		s.removeApplied(ref);
		expect(state().applied).toEqual({});
		await applied();
		s.setContext({ scanType: 'CT chest', history: 'new case' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS + 1);
		expect(state().applied ?? {}).toEqual({});
	});

	it('a value change marks the line "values"; a deleted finding marks it "finding"', async () => {
		await openedBts();
		await applied();
		s.edit(ref, 'size', '9 mm');
		api.calls.preview[0].resolve(ready({ draft: rows('solid', '9 mm') }));
		await flush();
		expect(state().applied?.[ref].stale).toBe('values');
		s.round([], false, G);
		await flush();
		expect(state().applied?.[ref].stale).toBe('finding');
	});

	it('columns apply under their own keys', async () => {
		const fl = card({ key: 'fleischner-pulmonary-nodule', name: 'Fleischner 2017', finding_id: 'u1', finding: A, siblings: ['bts-pulmonary-nodule'] });
		await matchA([fl]);
		s.open(cardRef(fl));
		for (const c of api.calls.open) c.resolve(ready());
		await flush();
		const a = `${cardRef(fl)}#fleischner-pulmonary-nodule`;
		const b = `${cardRef(fl)}#bts-pulmonary-nodule`;
		for (const k of [a, b]) {
			s.tick(k, 'kind', 'solid');
			s.apply(k);
			api.calls.calculate.at(-1)!.resolve({ calculation: calcOk(), ms: 3, error: null });
			await flush();
		}
		expect(Object.keys(state().applied ?? {}).sort()).toEqual([a, b].sort());
	});

	it('a pick left from before the card reached an outcome does not block Apply', async () => {
		await openedBts();
		s.pick(ref, 'pet'); // as if picked while several outcomes remained
		s.tick(ref, 'kind', 'solid');
		s.apply(ref);
		expect(api.calls.calculate).toHaveLength(1);
		api.calls.calculate[0].resolve({ calculation: calcOk(), ms: 3, error: null });
		await flush();
		expect(state().applied?.[ref]?.outcome).toBe('ct3');
	});
});
