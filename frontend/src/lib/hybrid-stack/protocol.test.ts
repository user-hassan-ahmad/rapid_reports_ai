import { describe, expect, it } from 'vitest';
import { assumedKey, backToLibrary, caseDirty, needsFreeText, pickBody, pickKey, pickSummary, visiblePills, withElsewhere, withoutRemoved, type ProtocolPick } from './protocol';
import { buildFindingsBlock, regionStates } from './regionState';
import type { GateRecord, StackUnit } from './types';

describe('visiblePills', () => {
	const groups = ['Technique', 'Right breast', 'Implants', 'Other findings', 'General', 'Conclusion'];
	it('hides a quiet region until something is placed there, in schema order', () => {
		expect(visiblePills(groups, ['Right breast'], ['Implants'], new Set())).toEqual(['Right breast']);
		expect(visiblePills(groups, ['Right breast'], ['Implants'], new Set(['Implants']))).toEqual(['Right breast', 'Implants']);
	});
	it('without quiet regions returns the pills unchanged', () => {
		expect(visiblePills(groups, ['Right breast'], [], new Set(['Implants']))).toEqual(['Right breast']);
	});
});

describe('withElsewhere', () => {
	const groups = { 'Lumbar levels': ['L4/5', 'L5/S1'] };
	const assumed = { 'Lumbar levels': ['No disc protrusion or neural compromise throughout the lumbar spine.'], Cord: ['Normal cord.'] };
	it('leaves the segment line alone when no level is dictated', () => {
		expect(withElsewhere(assumed, groups, new Set())).toEqual(assumed);
	});
	it('reads "Elsewhere, …" once a level in the segment is dictated', () => {
		expect(withElsewhere(assumed, groups, new Set(['L4/5']))['Lumbar levels']).toEqual([
			'Elsewhere, no disc protrusion or neural compromise throughout the lumbar spine.'
		]);
	});
	it('keeps an acronym capitalised', () => {
		const a = { 'Lumbar levels': ['MRI shows no stenosis.'] };
		expect(withElsewhere(a, groups, new Set(['L5/S1']))['Lumbar levels']).toEqual(['Elsewhere, MRI shows no stenosis.']);
	});
});

describe('pickBody', () => {
	it('is empty for free text and complete for a pick', () => {
		expect(pickBody(null)).toEqual({});
		expect(pickBody({ id: 'TMKN', phases: [], laterality: 'left', displayName: 'MRI Knee', line: 'No contrast' })).toEqual({
			protocol_id: 'TMKN', phases: [], laterality: 'left'
		});
	});
});

describe('pickKey', () => {
	const knee: ProtocolPick = { id: 'TMKN', phases: [], laterality: 'left', displayName: 'MRI Knee', line: 'No contrast' };
	it('is empty without a pick and changes with the id, the phases or the side', () => {
		expect(pickKey(null)).toBe('');
		const k = pickKey(knee);
		expect(pickKey({ ...knee })).toBe(k);
		expect(pickKey({ ...knee, laterality: 'right' })).not.toBe(k);
		expect(pickKey({ ...knee, phases: ['arterial'] })).not.toBe(k);
		expect(pickKey({ ...knee, id: 'TMKX' })).not.toBe(k);
		expect(pickKey({ ...knee, displayName: 'Other name' })).toBe(k); // display text is not identity
	});
});

describe('needsFreeText', () => {
	const pick: ProtocolPick = { id: 'TCAP', phases: ['portal_venous'], laterality: null, displayName: 'CT AP', line: 'IV contrast' };
	it('a scan type with no pick behind it shows as free text', () => {
		expect(needsFreeText('CT abdomen and pelvis', null)).toBe(true);
		expect(needsFreeText('CT abdomen and pelvis', pick)).toBe(false);
		expect(needsFreeText('   ', null)).toBe(false);
		expect(needsFreeText('', null)).toBe(false);
	});
});

describe('caseDirty', () => {
	const a: ProtocolPick = { id: 'TCAP', phases: ['portal_venous'], laterality: null, displayName: 'CT AP', line: 'IV contrast · portal venous' };
	const built = { scanType: 'CT AP', history: 'Pain', pick: a };
	it('is clean when the scan type, history and pick match what the workspace was built from', () => {
		expect(caseDirty({ scanType: ' CT AP ', history: 'Pain ', pick: { ...a } }, built)).toBe(false);
	});
	it('a different phase set or side is dirty even when the display name is the same', () => {
		expect(caseDirty({ ...built, pick: { ...a, phases: ['arterial', 'portal_venous'] } }, built)).toBe(true);
		expect(caseDirty({ ...built, pick: { ...a, laterality: 'left' } }, built)).toBe(true);
	});
	it('switching between a pick and free text is dirty; free text compares as before', () => {
		expect(caseDirty({ ...built, pick: null }, built)).toBe(true);
		const free = { scanType: 'US abdomen', history: 'Pain', pick: null };
		expect(caseDirty({ ...free }, free)).toBe(false);
		expect(caseDirty({ ...free, scanType: 'US pelvis' }, free)).toBe(true);
		expect(caseDirty({ ...free, history: 'Fever' }, free)).toBe(true);
	});
});

describe('quiet regions in the gate', () => {
	const u = (id: number, text: string, group: string | null): StackUnit => ({
		id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false
	});
	const groups = ['Technique', 'Right breast', 'Implants', 'Other findings', 'General', 'Conclusion'];
	const gate = (assumedNormal: string[]): GateRecord => ({
		confirmed_at: 't', conclusion_text: '', conclusion_source: 'draft', assumed_normal: assumedNormal, remainder_normal: [],
		dictated_normal: [], units_hash: 'h', items: [], assumed: {}, removed: [], capped: []
	});
	it('an undictated quiet region is never named as confirmed normal (regionView from the shown pills)', () => {
		const units = [u(0, 'No suspicious enhancement.', 'Right breast')];
		const shown = visiblePills(groups, ['Right breast'], ['Implants'], new Set(['Right breast']));
		const view = regionStates(units, shown);
		expect(view.assumedNormal).not.toContain('Implants');
		expect(buildFindingsBlock(units, groups, gate(view.assumedNormal))).not.toContain('Implants');
	});
	it('a quiet region with something placed there takes part as any other', () => {
		const units = [u(0, 'Intact implants.', 'Implants')];
		const shown = visiblePills(groups, ['Right breast'], ['Implants'], new Set(['Implants']));
		expect(regionStates(units, shown).dictatedNormal.map((d) => d.region)).toEqual(['Implants']);
	});
});

describe('removing and editing an "Elsewhere, …" line', () => {
	const groups = { 'Lumbar levels': ['L4/5', 'L5/S1'] };
	const raw = 'No disc protrusion or neural compromise throughout the lumbar spine.';
	const assumed = { 'Lumbar levels': [raw], Cord: ['Normal cord.'] };
	const shown = (removed: string[]) => withoutRemoved(withElsewhere(assumed, groups, new Set(['L4/5'])), removed);
	it('× on the "Elsewhere, …" form removes it', () => {
		const line = shown([])['Lumbar levels'][0];
		expect(line.startsWith('Elsewhere, ')).toBe(true);
		expect(shown([line])).toEqual({ Cord: ['Normal cord.'] });
	});
	it('a removal of the raw form also removes the "Elsewhere, …" form, and the reverse', () => {
		expect(shown([raw])['Lumbar levels']).toBeUndefined();
		expect(withoutRemoved(assumed, [`Elsewhere, ${raw[0].toLowerCase()}${raw.slice(1)}`])['Lumbar levels']).toBeUndefined();
		expect(assumedKey(`Elsewhere, ${raw}`)).toBe(assumedKey(raw));
	});
	it('an edit replaces the original: the original is removed and the edited text is not assumed alongside it', () => {
		const original = shown([])['Lumbar levels'][0];
		const after = shown([original]); // editAssumed removes the original; the edit joins the dictation
		expect(Object.values(after).flat()).not.toContain(original);
		expect(Object.values(after).flat().some((x) => assumedKey(x) === assumedKey(raw))).toBe(false);
	});
	it('is idempotent: withElsewhere on a reply already in "Elsewhere, …" form leaves it unchanged', () => {
		const once = withElsewhere(assumed, groups, new Set(['L4/5']));
		expect(withElsewhere(once, groups, new Set(['L4/5']))).toEqual(once);
		expect(withoutRemoved(withoutRemoved(once, [raw]), [raw])).toEqual(withoutRemoved(once, [raw]));
	});
	it('what /assumed is sent: the "Elsewhere, …" sentence for a segment with a dictated level, raw otherwise', () => {
		expect(withElsewhere(assumed, groups, new Set(['L4/5']))['Lumbar levels']).toEqual([
			'Elsewhere, no disc protrusion or neural compromise throughout the lumbar spine.']);
		expect(withElsewhere(assumed, groups, new Set())['Lumbar levels']).toEqual([raw]);
	});
});

describe('pickSummary', () => {
	it('names the pick with its side, and carries the protocol line', () => {
		expect(pickSummary({ id: 'TMKN', phases: [], laterality: 'left', displayName: 'MRI Knee', line: 'No contrast' }))
			.toEqual({ name: 'MRI Knee (left)', line: 'No contrast' });
		expect(pickSummary({ id: 'TCAP', phases: ['portal_venous'], laterality: null, displayName: 'CT AP', line: 'IV contrast · portal venous' }).name)
			.toBe('CT AP');
	});
});

describe('backToLibrary', () => {
	it('moves the typed text to the search box and empties the scan type, so free text does not come straight back', () => {
		const b = backToLibrary(' US abdomen ');
		expect(b).toEqual({ query: 'US abdomen', scanType: '', pick: null, freeText: false });
		expect(needsFreeText(b.scanType, b.pick)).toBe(false);
	});
});
