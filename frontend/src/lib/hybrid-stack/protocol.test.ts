import { describe, expect, it } from 'vitest';
import { needsFreeText, pickBody, pickKey, visiblePills, withElsewhere, type ProtocolPick } from './protocol';

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
