import { describe, expect, it } from 'vitest';
import { assumedKey, backToLibrary, caseDirty, needsFreeText, pickBody, pickKey, pickSummary, shownNormals, visiblePills, withElsewhere, withoutRemoved, withoutSegments, withSegmentNormals, type ProtocolPick } from './protocol';
import { buildFindingsBlock, regionStates } from './regionState';
import type { GateRecord, StackUnit } from './types';

const u = (id: number, text: string, group: string | null, abnormal = false): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal, pinned: false, heading: false
});
const gate = (assumedNormal: string[]): GateRecord => ({
	confirmed_at: 't', conclusion_text: '', conclusion_source: 'draft', assumed_normal: assumedNormal, remainder_normal: [],
	dictated_normal: [], units_hash: 'h', items: [], assumed: {}, removed: [], capped: []
});

describe('visiblePills', () => {
	const groups = ['Technique', 'Right breast', 'Implants', 'Other findings', 'General', 'Conclusion'];
	it('hides a quiet region until something is placed there, in schema order', () => {
		expect(visiblePills(groups, ['Right breast'], ['Implants'], new Set())).toEqual(['Right breast']);
		expect(visiblePills(groups, ['Right breast'], ['Implants'], new Set(['Implants']))).toEqual(['Right breast', 'Implants']);
	});
	it('without quiet regions returns the pills unchanged', () => {
		expect(visiblePills(groups, ['Right breast'], [], new Set(['Implants']))).toEqual(['Right breast']);
	});
	it('drops a quiet region the pills carry unless something is placed there (the scratchpad passes every region)', () => {
		const spine = ['Technique', 'Cord', 'Cervical levels', 'C2/3', 'C3/4', 'Lumbar levels', 'L4/5', 'L5/S1', 'Other findings'];
		const pills = spine.filter((g) => g !== 'Other findings'); // pillRegions: every stack region but Other
		const quiet = ['C2/3', 'C3/4', 'L4/5', 'L5/S1'];
		expect(visiblePills(spine, pills, quiet, new Set())).toEqual(['Technique', 'Cord', 'Cervical levels', 'Lumbar levels']);
		expect(visiblePills(spine, pills, quiet, new Set(['L4/5']))).toEqual(['Technique', 'Cord', 'Cervical levels', 'Lumbar levels', 'L4/5']);
		const view = regionStates([u(0, 'Broad-based disc bulge at L4/5.', 'L4/5', true)], visiblePills(spine, pills, quiet, new Set(['L4/5'])));
		expect(view.assumedNormal).toEqual(['Technique', 'Cord', 'Cervical levels', 'Lumbar levels']);
	});
});

describe('segment normals (E1: decided here, never by the /assumed check)', () => {
	const levelGroups = { 'Cervical levels': ['C2/3', 'C3/4'], 'Lumbar levels': ['L4/5', 'L5/S1'] };
	const cervical = 'The cervical discs, spinal canal and exit foramina are normal throughout.';
	const lumbar = 'The lumbar discs, spinal canal and exit foramina are normal throughout.';
	const normals = { Cord: ['Normal cord signal.'], 'Cervical levels': [cervical], 'Lumbar levels': [lumbar] };
	const untouched = ['Cord', 'Cervical levels', 'Lumbar levels'];
	it('the /assumed body carries no segment region', () => {
		expect(withoutSegments(normals, levelGroups)).toEqual({ Cord: ['Normal cord signal.'] });
		expect(withoutSegments(normals, {})).toEqual(normals);
	});
	it('an untouched segment is offered from the sheet, beside the checked normals', () => {
		expect(withSegmentNormals({ Cord: ['Normal cord signal.'] }, normals, levelGroups, untouched)).toEqual(normals);
	});
	it('a segment with something placed in its own region offers nothing', () => {
		expect(withSegmentNormals({}, normals, levelGroups, ['Cord', 'Cervical levels'])).toEqual({ 'Cervical levels': [cervical] });
	});
	it('a stale checked answer for a segment never wins over the sheet', () => {
		expect(withSegmentNormals({ 'Lumbar levels': [] }, normals, levelGroups, untouched)['Lumbar levels']).toEqual([lumbar]);
		expect(withSegmentNormals({ 'Lumbar levels': ['x'] }, normals, levelGroups, ['Cord'])['Lumbar levels']).toBeUndefined();
	});
	it('the live repro: a dictated L4/5 keeps every segment, the lumbar one as "Elsewhere, …"', () => {
		const shown = shownNormals({ Cord: ['Normal cord signal.'] }, normals, levelGroups, untouched, new Set(['L4/5']), []);
		expect(shown).toEqual({
			Cord: ['Normal cord signal.'],
			'Cervical levels': [cervical],
			'Lumbar levels': ['Elsewhere, the lumbar discs, spinal canal and exit foramina are normal throughout.']
		});
	});
	it('× on either form removes the segment line; a removed checked normal stays removed', () => {
		const placed = new Set(['L4/5']);
		const elsewhere = shownNormals({}, normals, levelGroups, untouched, placed, [])['Lumbar levels'][0];
		expect(shownNormals({}, normals, levelGroups, untouched, placed, [elsewhere])['Lumbar levels']).toBeUndefined();
		expect(shownNormals({}, normals, levelGroups, untouched, placed, [lumbar])['Lumbar levels']).toBeUndefined();
		expect(shownNormals({ Cord: ['Normal cord signal.'] }, normals, levelGroups, untouched, placed, ['Normal cord signal.']).Cord).toBeUndefined();
	});
	it('reaches the gate record: the findings block states the segment lines', () => {
		const shown = shownNormals({}, normals, levelGroups, ['Cervical levels', 'Lumbar levels'], new Set(['L4/5']), []);
		const groups = ['Cervical levels', 'Lumbar levels', 'L4/5'];
		const units = [u(0, 'Broad-based disc bulge at L4/5.', 'L4/5', true)];
		const block = buildFindingsBlock(units, groups, { ...gate([]), assumed: shown });
		expect(block).toContain(cervical);
		expect(block).toContain('Elsewhere, the lumbar discs');
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
	const groups = ['Technique', 'Right breast', 'Implants', 'Other findings', 'General', 'Conclusion'];
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
	it('the segment line reads "Elsewhere, …" with a dictated level, raw otherwise; /assumed never sees it', () => {
		expect(withElsewhere(assumed, groups, new Set(['L4/5']))['Lumbar levels']).toEqual([
			'Elsewhere, no disc protrusion or neural compromise throughout the lumbar spine.']);
		expect(withElsewhere(assumed, groups, new Set())['Lumbar levels']).toEqual([raw]);
		expect(withoutSegments(assumed, groups)).toEqual({ Cord: ['Normal cord.'] });
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
