import { describe, expect, it } from 'vitest';
import { abnormalAll, anchorRegion, answerLabel, assumedFrom, assumedStale, addedAtConfirm, confirmReady, confirmRecheckFailed, flaggedFrom, gateKeyOf, isFlagged, keepRules, moreLine, openCount, quietLine, rowSentences, rulesToSend, splitReply, unansweredChecks } from './items';
import type { StackItem, StackUnit } from './types';

const item = (id: string, sentences: string[], extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'finding', region: 'Pelvic organs', question: 'Ovarian torsion?', why: '', sentences, answered: false, ...extra
});

describe('checklist rows', () => {
	it('labels the answer "✓ Normal" however many wordings sit beside it', () => {
		expect(answerLabel(['No features of torsion.'])).toBe('✓ Normal');
		expect(answerLabel(['No torsion.', 'No rupture.', 'No haemorrhage.'])).toBe('✓ Normal');
	});
	it('anchors a finding check under the region of the sentence that set it off', () => {
		const unit = (id: number, text: string, group: string): StackUnit => ({
			id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: true, pinned: false, heading: false
		});
		const units = [unit(0, 'A 3 cm hypoenhancing mass in the pancreatic head.', 'Pancreas'), unit(1, 'It abuts the SMV.', 'Vessels')];
		expect(anchorRegion(item('a', ['x.'], { region: 'Pancreas', source_text: 'abuts the SMV' }), units)).toBe('Vessels');
		expect(anchorRegion(item('b', ['x.'], { region: 'Liver', source_text: 'not dictated' }), units)).toBe('Liver');
	});
	it('a row lists only the sentences the radiologist has not removed', () => {
		expect(rowSentences(item('a', ['No torsion.', 'No rupture.']), ['no rupture'])).toEqual(['No torsion.']);
	});
	it('only referral rows block; finding checks left unanswered are counted, never blocking', () => {
		const ref = (id: string, s: string[], x: Partial<StackItem> = {}) => item(id, s, { kind: 'referral', ...x });
		const items = [ref('a', ['x.']), ref('b', [], { answered: true }), ref('c', ['y.']), ref('d', ['z.']), ref('e', ['w.']),
			item('f', ['v.']), item('g', ['u.'])];
		expect(openCount(items, ['c'], ['z.'], ['e'])).toBe(1);
		expect(unansweredChecks(items, [], [], ['g'])).toBe(1);
	});
	it('caps the quiet line at three with a count of the rest', () => {
		expect(quietLine(['a', 'b', 'c', 'd', 'e'])).toEqual({ shown: ['a', 'b', 'c'], more: 2 });
		expect(quietLine(['a'])).toEqual({ shown: ['a'], more: 0 });
	});
	it('collects every abnormal sentence (parts included) as the writer cache key', () => {
		const u = (id: number, text: string, extra: Partial<StackUnit>): StackUnit => ({
			id, text, group: 'Liver', structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
		});
		expect(abnormalAll([u(0, 'A cyst.', { abnormal: true }), u(1, 'Kidneys normal.', { group: 'Kidneys' }),
			u(2, 'Spleen normal and a gallstone.', { parts: [{ text: 'Spleen normal', group: 'Spleen' }, { text: 'and a gallstone.', group: 'Gallbladder', abnormal: true }] })]))
			.toEqual(['A cyst.', 'and a gallstone.']);
	});
	it('assumes only what /assumed answered for the region as it is now; removed sentences never', () => {
		const snap = { offered: {}, dictation: 'x', abnormal: ['Spleen'], untouched: ['Liver', 'Bowel'],
			assumed: { Liver: ['The liver is normal.'], Bowel: [], Spleen: ['The spleen is normal.', 'No splenic lesion.'] } };
		expect(assumedFrom(snap, ['Spleen'], ['Liver', 'Bowel', 'Appendix'], ['no splenic lesion']))
			.toEqual({ Spleen: ['The spleen is normal.'], Liver: ['The liver is normal.'] });
		// Liver turned abnormal since the answer: its untouched normals are no longer assumed
		expect(assumedFrom(snap, ['Spleen', 'Liver'], ['Bowel'], [])).toEqual({ Spleen: ['The spleen is normal.', 'No splenic lesion.'] });
		expect(assumedFrom(null, ['Spleen'], [], [])).toEqual({});
	});
	it('a dictated-normal region keeps the sentences the check left, compared with its state in the snapshot (R2)', () => {
		const snap = { offered: {}, dictation: 'x', abnormal: [], untouched: ['Menisci'], dictatedNormal: ['Ligaments'],
			assumed: { Ligaments: ['The posterior cruciate ligament is intact.'], Menisci: ['The menisci are intact.'] } };
		expect(assumedFrom(snap, [], ['Menisci'], [], ['Ligaments']))
			.toEqual({ Ligaments: ['The posterior cruciate ligament is intact.'], Menisci: ['The menisci are intact.'] });
		// Menisci dictated normal since the answer (checked untouched): not assumed until checked in that state
		expect(assumedFrom(snap, [], [], [], ['Ligaments', 'Menisci'])).toEqual({ Ligaments: ['The posterior cruciate ligament is intact.'] });
		// Ligaments turned abnormal since: its dictated-normal answer no longer holds
		expect(assumedFrom(snap, ['Ligaments'], ['Menisci'], [], [])).toEqual({ Menisci: ['The menisci are intact.'] });
		// an older snapshot without dictated-normal regions assumes nothing for them
		expect(assumedFrom({ ...snap, dictatedNormal: undefined }, [], ['Menisci'], [], ['Ligaments'])).toEqual({ Menisci: ['The menisci are intact.'] });
	});
	it('keeps the flagged sentences in the snapshot: only those still assumed, in the state they were checked for (R1)', () => {
		const snap = { offered: {}, dictation: 'x', abnormal: ['Spleen'], untouched: ['Liver'],
			assumed: { Liver: ['The liver is normal.'], Spleen: ['The spleen is normal.', 'No splenic lesion.'] },
			flagged: { Liver: ['The liver is normal.'], Spleen: ['No splenic lesion.'] } };
		// keyed by region (round 1): the same words in another region are not flagged
		expect(flaggedFrom(snap, ['Spleen'], ['Liver'], [])).toEqual({ Spleen: ['No splenic lesion.'], Liver: ['The liver is normal.'] });
		expect(flaggedFrom(snap, ['Spleen'], ['Liver'], ['no splenic lesion'])).toEqual({ Liver: ['The liver is normal.'] });   // removed with ×
		expect(flaggedFrom(snap, ['Spleen', 'Liver'], [], [])).toEqual({ Spleen: ['No splenic lesion.'] });   // Liver changed state since
		expect(flaggedFrom({ ...snap, flagged: undefined }, ['Spleen'], ['Liver'], [])).toEqual({});
		expect(flaggedFrom(null, ['Spleen'], [], [])).toEqual({});
	});
	it('rows over the cap wait behind "N more checks": N counts the rows still asked; the line stays for a tapped one', () => {
		const capped = [item('c1', ['No free fluid.']), item('c2', ['No collection.']), item('c3', ['No fistula.']), item('c4', ['No abscess.'])];
		// c1 was promoted onto the checklist by a later reply; c3 was skipped; c4 tapped
		const m = moreLine(capped, [item('a', ['x']), item('c1', ['No free fluid.'])], ['c4'], [], ['c3']);
		expect(m.rows.map((r) => r.id)).toEqual(['c2', 'c4']);
		expect(m).toMatchObject({ waiting: 1, show: true });
		expect(moreLine(capped.slice(3), [], ['c4'], [], [])).toMatchObject({ waiting: 0, show: true });   // only a tapped one
		expect(moreLine([item('c2', ['No collection.'])], [], [], ['no collection'], [])).toMatchObject({ waiting: 0, show: false });   // removed with ×
		expect(moreLine([], [item('a', ['x'])], [], [], [])).toEqual({ rows: [], waiting: 0, show: false });
	});
	it('a reply is split by where each row was: answered capped rows fold behind the line; a re-check never moves one', () => {
		const res = {
			items: [item('a', ['No torsion.']), item('c1', [], { answered: true }), item('c2', ['No collection.'])], // c2 promoted by the caps
			capped: [item('c3', ['No fistula.'])]
		};
		const re = splitReply(res, ['c1', 'c2', 'c3'], ['a'], true);
		expect(re.items.map((r) => r.id)).toEqual(['a']);
		expect(re.capped.map((r) => r.id)).toEqual(['c1', 'c2', 'c3']);
		const full = splitReply(res, ['c1', 'c2', 'c3'], ['a'], false);
		expect(full.items.map((r) => r.id)).toEqual(['a', 'c2']);   // the full reply's caps may promote one
		expect(full.capped.map((r) => r.id)).toEqual(['c1', 'c3']);   // answered behind the line: folds there
		// a re-check's caps pushed out an open row: it stays on the checklist, never lost
		const pushed = splitReply({ items: [], capped: [item('a', ['x']), item('c3', ['No fistula.'])] }, ['c3'], ['a'], true);
		expect(pushed.items.map((r) => r.id)).toEqual(['a']);
		expect(pushed.capped.map((r) => r.id)).toEqual(['c3']);
		expect(splitReply({ items: [item('a', ['x'])], capped: [] }, [], [], true)).toEqual({ items: [item('a', ['x'])], capped: [] });
	});
});

describe('assumed normals before any dictation (E6)', () => {
	const snap = { dictation: '', abnormal: [], untouched: ['Cord', 'Alignment'], offered: { Cord: ['Normal cord.'], Alignment: ['Normal alignment.'] },
		assumed: { Cord: ['Normal cord.'], Alignment: ['Normal alignment.'] } };
	it('the answer for the empty dictation renders every untouched region', () => {
		expect(assumedFrom(snap, [], ['Cord', 'Alignment'], [])).toEqual(snap.assumed);
	});
	it('is current for the empty dictation, behind once something is dictated, and never behind without a sheet', () => {
		expect(assumedStale(true, snap, '')).toBe(false);
		expect(assumedStale(true, null, '')).toBe(true);
		expect(assumedStale(true, snap, 'At L4/5 there is a disc bulge.')).toBe(true);
		expect(assumedStale(false, null, '')).toBe(false);
	});
	it('a failed answer for the empty dictation is behind again, up to three tries (round 1: the rule call can fail)', () => {
		const failed = { ...snap, assumed: {}, check_failed: true };
		expect(assumedStale(true, failed, '')).toBe(true);
		expect(assumedStale(true, { ...failed, failures: 2 }, '')).toBe(true);
		expect(assumedStale(true, { ...failed, failures: 3 }, '')).toBe(false);
		// once something is dictated a failure fails open, as before: Confirm is not held
		const said = { ...failed, dictation: 'A liver cyst.' };
		expect(assumedStale(true, said, 'A liver cyst.')).toBe(false);
	});
});

describe('template context rules decided once per session (R5)', () => {
	const ok = { rules: { 'no previous study is available': 0.9 }, error: null };
	it('the first good reply is kept for the history it was decided from, and sent back on every refresh', () => {
		expect(rulesToSend(null, 'Headache.')).toBeNull(); // nothing decided: the server decides now
		const kept = keepRules(null, 'Headache.', ok);
		expect(kept).toEqual({ history: 'Headache.', rules: ok.rules });
		expect(rulesToSend(kept, 'Headache.')).toEqual(ok.rules);
		// later replies never replace the session's decision
		expect(keepRules(kept, 'Headache.', { rules: { 'no previous study is available': 0.1 }, error: null })).toBe(kept);
	});
	it('a failed reply keeps nothing; an edited history is decided again', () => {
		expect(keepRules(null, 'Headache.', { rules: null, error: 'RuntimeError: down' })).toBeNull();
		expect(keepRules(null, 'Headache.', { rules: { x: 0.9 }, error: 'RuntimeError: down' })).toBeNull();
		const kept = keepRules(null, 'Headache.', ok);
		expect(rulesToSend(kept, 'Headache. Prior MRI 2024.')).toBeNull();
		expect(keepRules(kept, 'Headache. Prior MRI 2024.', { rules: { x: 0.1 }, error: null }))
			.toEqual({ history: 'Headache. Prior MRI 2024.', rules: { x: 0.1 } });
	});
});

describe('Confirm gates only on a Confirm answer for this dictation (round 1)', () => {
	const snap = { offered: {}, dictation: 'A liver cyst.', abnormal: ['Liver'], untouched: [], assumed: {} };
	it('a live answer, or a Confirm answer for another dictation, is not enough', () => {
		expect(confirmReady(null, 'A liver cyst.')).toBe(false);
		expect(confirmReady(snap, 'A liver cyst.')).toBe(false);
		expect(confirmReady({ ...snap, confirmed: true }, 'A liver cyst. Gallstones.')).toBe(false);
		expect(confirmReady({ ...snap, confirmed: true }, 'A liver cyst.')).toBe(true);
	});
});

describe('Confirm re-ask failure and the gate key (re-review minors)', () => {
	const live = { offered: {}, dictation: 'A liver cyst.', abnormal: ['Liver'], untouched: [], assumed: { Liver: ['No biliary dilatation.'] } };
	it('a Confirm re-ask that failed where the live answer had not stops Confirm', () => {
		const failed = { ...live, assumed: {}, check_failed: true, confirmed: true };
		expect(confirmRecheckFailed(live, failed)).toBe(true);
		expect(confirmRecheckFailed(live, { ...live, confirmed: true })).toBe(false);
		// the live answer had failed too: the failure fails open, as before
		expect(confirmRecheckFailed({ ...live, assumed: {}, check_failed: true }, failed)).toBe(false);
		// a failed live refresh is not a Confirm answer
		expect(confirmRecheckFailed(live, { ...failed, confirmed: false })).toBe(false);
	});
	it('the gate key changes with the scan type, so a recorded gate never survives a scan-type change', () => {
		const parts = ['A liver cyst.', '[]', '{}'];
		expect(gateKeyOf('CT abdomen', parts)).toBe(gateKeyOf('CT abdomen', [...parts]));
		expect(gateKeyOf('CT abdomen', parts)).not.toBe(gateKeyOf('MRI abdomen', parts));
		expect(gateKeyOf('', ['a', 'b'])).not.toBe(gateKeyOf('a', ['b']));
	});
});

describe('a Confirm answer that adds anything is shown before it is gated (round 1)', () => {
	const before = { assumed: { Liver: ['The liver is normal.'], Brain: ['The ventricles are normal.'] }, flagged: {} };
	it('removals only: nothing added, Confirm proceeds', () => {
		expect(addedAtConfirm(before, { assumed: { Liver: ['The liver is normal.'] }, flagged: {} })).toEqual([]);
		expect(addedAtConfirm(before, { assumed: { Liver: ['the liver is normal'], Brain: ['The ventricles are normal.'] }, flagged: {} })).toEqual([]);
	});
	it('a sentence un-hidden by a rule, or one newly flagged, is added', () => {
		const prior = 'No interval change compared with the previous MRI.';
		expect(addedAtConfirm(before, { assumed: { ...before.assumed, Brain: ['The ventricles are normal.', prior] }, flagged: {} })).toEqual([prior]);
		expect(addedAtConfirm(before, { assumed: before.assumed, flagged: { Liver: ['The liver is normal.'] } })).toEqual(['The liver is normal.']);
		// the same words moving to another region count as added there
		expect(addedAtConfirm(before, { assumed: { Spleen: ['The liver is normal.'] }, flagged: {} })).toEqual(['The liver is normal.']);
	});
	it('isFlagged reads a sentence in one of the given regions, by its normalised text', () => {
		const flagged = { Kidneys: ['The kidneys are normal.'] };
		expect(isFlagged(flagged, ['Kidneys'], 'the kidneys are normal')).toBe(true);
		expect(isFlagged(flagged, ['Liver'], 'The kidneys are normal.')).toBe(false);
	});
});
