import { describe, expect, it } from 'vitest';
import { assumedKey, backToLibrary, caseDirty, needsFreeText, pickBody, pickKey, pickSummary, asTailUnits, blockedSegments, placedRegions, segmentBlocked, shownNormals, visiblePills, withElsewhere, withoutRemoved, withoutSegments, withSegmentNormals, type ProtocolPick } from './protocol';
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

describe('placedRegions (every split part counts)', () => {
	it('a level placed as a later part of a split sentence is placed', () => {
		const split: StackUnit = { ...u(0, 'Normal cord signal, and at L4/5 there is a broad-based disc bulge.', 'Cord'),
			parts: [{ text: 'Normal cord signal', group: 'Cord' }, { text: 'at L4/5 there is a broad-based disc bulge.', group: 'L4/5', abnormal: true }] };
		const placed = placedRegions([split]);
		expect([...placed].sort()).toEqual(['Cord', 'L4/5']);
		const spine = ['Cord', 'Lumbar levels', 'L4/5', 'L5/S1'];
		expect(visiblePills(spine, spine, ['L4/5', 'L5/S1'], placed)).toEqual(['Cord', 'Lumbar levels', 'L4/5']);
		const lumbar = 'The lumbar discs are normal throughout.';
		expect(shownNormals({}, { 'Lumbar levels': [lumbar] }, { 'Lumbar levels': ['L4/5', 'L5/S1'] }, ['Lumbar levels'], placed, [])['Lumbar levels'])
			.toEqual(['Elsewhere, the lumbar discs are normal throughout.']);
	});
	it('headings and unplaced units place nothing', () => {
		expect(placedRegions([u(0, 'Findings', 'Cord'), u(1, 'tail', null)].map((x, k) => (k === 0 ? { ...x, heading: true } : x))).size).toBe(0);
	});
});

describe('segment backstop for misfiled findings (errs toward omission)', () => {
	const levelGroups = { 'Cervical levels': ['C4/5', 'C5/6'], 'Thoracic levels': ['T11/12', 'T12/L1'], 'Lumbar levels': ['L4/5', 'L5/S1'] };
	const normals = { 'Cervical levels': ['Cervical normal.'], 'Thoracic levels': ['Thoracic normal.'], 'Lumbar levels': ['Lumbar normal.'] };
	const segs = Object.keys(levelGroups);
	const blocked = (units: StackUnit[]) => [...blockedSegments(levelGroups, units)].sort();
	it('a C5/6 finding filed under Cord withholds Cervical only', () => {
		const units = [u(0, 'Disc osteophyte complex at C5/6 indenting the cord.', 'Cord', true)];
		expect(blocked(units)).toEqual(['Cervical levels']);
		expect(Object.keys(shownNormals({}, normals, levelGroups, segs, placedRegions(units), [], blockedSegments(levelGroups, units))))
			.toEqual(['Thoracic levels', 'Lumbar levels']);
	});
	it('"multilevel degenerative disc disease" in General withholds all three', () => {
		expect(blocked([u(0, 'Multilevel degenerative disc disease.', 'General', true)])).toEqual(segs.slice().sort());
		expect(blocked([u(0, 'Multi-level facet arthropathy.', 'Other findings', true)])).toEqual(segs.slice().sort());
	});
	it('"multilevel" naming a segment or a level withholds only those segments (review reversal)', () => {
		expect(blocked([u(0, 'Multilevel lumbar spondylosis.', 'General', true)])).toEqual(['Lumbar levels']);
		expect(blocked([u(0, 'Multilevel disc bulges from C4/5 to C5/6.', 'Other findings', true)])).toEqual(['Cervical levels']);
		expect(blocked([u(0, 'Multilevel thoracolumbar spondylosis.', 'General', true)])).toEqual(['Lumbar levels', 'Thoracic levels']);
		expect(blocked([u(0, 'Multilevel facet arthropathy, worst at L4/5.', 'L4/5', true)])).toEqual(['Lumbar levels']);   // own region too
		expect(blocked([u(0, 'Multilevel degenerative disc disease.', 'General', true)])).toEqual(segs.slice().sort());   // bare: all
	});
	it('an L4/5 bulge filed in L4/5 withholds nothing; Lumbar reads "Elsewhere, …"', () => {
		const units = [u(0, 'At L4/5 there is a broad-based disc bulge.', 'L4/5', true)];
		expect(blocked(units)).toEqual([]);
		expect(shownNormals({}, normals, levelGroups, segs, placedRegions(units), [], blockedSegments(levelGroups, units))['Lumbar levels'])
			.toEqual(['Elsewhere, lumbar normal.']);
	});
	it('a normal mention withholds nothing ("normal cervical lordosis")', () => {
		expect(blocked([u(0, 'Normal cervical lordosis.', 'Alignment')])).toEqual([]);
	});
	it('an ungrouped tail unit counts whatever its flag (its state is not known yet); a split part counts when abnormal', () => {
		expect(blocked([u(0, 'Lumbar canal stenosis.', null, true)])).toEqual(['Lumbar levels']);
		expect(blocked([u(0, 'Lumbar canal stenosis at L4/5.', null)])).toEqual(['Lumbar levels']);
		expect(blocked([u(0, 'Normal cervical lordosis.', null)])).toEqual(['Cervical levels']);
		expect(blocked([u(0, 'Normal cervical lordosis.', 'Alignment')])).toEqual([]);
		const split: StackUnit = { ...u(1, 'Normal cord; T12/L1 disc extrusion.', 'Cord'),
			parts: [{ text: 'Normal cord', group: 'Cord' }, { text: 'T12/L1 disc extrusion.', group: 'Cord', abnormal: true }] };
		expect(blocked([split])).toEqual(['Lumbar levels', 'Thoracic levels']); // T12/L1 names the L1 vertebra too
	});
	it('level labels match in every common format, and only whole labels', () => {
		const hit = (t: string) => segmentBlocked('Cervical levels', ['C5/6'], [{ group: 'Cord', text: t }]);
		for (const t of ['at C5/6', 'C5-6 protrusion', 'C5-C6 protrusion', 'c5 / 6', 'C5–6']) expect(hit(t)).toBe(true);
		for (const t of ['AC5/6', 'C15/6', 'L5/6']) expect(hit(t)).toBe(false); // "C5/67" still names the C5 vertebra
		expect(segmentBlocked('Lumbar levels', ['L5/S1'], [{ group: 'Cord', text: 'L5-S1 annular fissure' }])).toBe(true);
		expect(segmentBlocked('Lumbar levels', ['L4/5'], [{ group: 'Cord', text: 'lumbosacral junction transitional anomaly' }])).toBe(true);
		expect(segmentBlocked('Thoracic levels', ['T12/L1'], [{ group: 'Cord', text: 'T12-L1 disc' }])).toBe(true);
	});
	it('"thoracolumbar" names thoracic and lumbar, "cervicothoracic" cervical and thoracic, as whole words in any case', () => {
		expect(blocked([u(0, 'Thoracolumbar junction kyphosis.', 'Alignment', true)])).toEqual(['Lumbar levels', 'Thoracic levels']);
		expect(blocked([u(0, 'CERVICOTHORACIC scoliosis.', 'Alignment', true)])).toEqual(['Cervical levels', 'Thoracic levels']);
		expect(blocked([u(0, 'Subthoracolumbarish artefact.', 'Alignment', true)])).toEqual([]);
	});
	it('the live tail (never grouped) withholds too, and the gate record built with it holds no Lumbar line', () => {
		const tail = asTailUnits(['Disc extrusion at L4/5 compressing the L5 root.']);
		expect(tail[0].group).toBeNull();
		expect(blocked([u(0, 'Normal cord signal.', 'Cord'), ...tail])).toEqual(['Lumbar levels']);
		const units = [u(0, 'Normal cord signal.', 'Cord')];
		const assumed = shownNormals({}, normals, levelGroups, segs, placedRegions(units), [], blockedSegments(levelGroups, [...units, ...tail]));
		expect(Object.keys(assumed)).toEqual(['Cervical levels', 'Thoracic levels']);
		const block = buildFindingsBlock([...units, ...tail], ['Cord', ...segs], { ...gate([]), assumed });
		expect(block).toContain('Disc extrusion at L4/5');
		expect(block).not.toContain('Lumbar normal.');
	});
	it('a single vertebra of the segment withholds its line, as a whole token', () => {
		expect(blocked([u(0, 'Grade 1 anterolisthesis of L4 on L5.', 'General', true)])).toEqual(['Lumbar levels']);
		expect(blocked([u(0, 'T7 haemangioma.', 'Alignment', true)])).toEqual(['Thoracic levels']);
		expect(blocked([u(0, 'Bilateral L5 pars defects.', 'General', true)])).toEqual(['Lumbar levels']);
		expect(blocked([u(0, 'S1 nerve root sleeve cyst.', 'Other findings', true)])).toEqual(['Lumbar levels']);
		expect(blocked([u(0, 'C2 odontoid fracture.', 'General', true)])).toEqual(['Cervical levels']);
		for (const t of ['T13 rib.', 'L6 segment.', 'C8 radiculopathy.', 'AL4 lesion.', 'C55 note.']) expect(blocked([u(0, t, 'General', true)])).toEqual([]);
	});
	it('a T1/T2 MR sequence name is not a vertebra', () => {
		for (const t of ['T2 hyperintense cord lesion.', 'T2-weighted signal change in the cord.', 'Low T1 signal in the cord.', 'T1 post-contrast enhancement.', 'T2W hyperintensity.', 'STIR and T2 high signal.'])
			expect(blocked([u(0, t, 'Cord', true)])).toEqual([]);
		expect(blocked([u(0, 'T2 vertebral body fracture.', 'General', true)])).toEqual(['Thoracic levels']);
	});
	it('a sentence inside the segment\'s own regions does not withhold it, except "multilevel"', () => {
		expect(segmentBlocked('Lumbar levels', ['L4/5'], [{ group: 'L4/5', text: 'Lumbar disc bulge at L4/5.' }])).toBe(false);
		expect(segmentBlocked('Lumbar levels', ['L4/5'], [{ group: 'L4/5', text: 'Multilevel disc bulges, worst at L4/5.' }])).toBe(true);
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
