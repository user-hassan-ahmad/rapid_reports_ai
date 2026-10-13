import { describe, expect, it } from 'vitest';
import {
	blockingValues, chipLabel, enterValue, failFill, filledItems, initialChips, isFilling, keepStated, markNa, markRestNa, mergeFill,
	naItems, startFill, valueStatements, valuesBody, valuesKey
} from './values';
import type { ValueChip } from './types';

const ITEMS = ['LVEF', 'LVEDVi', 'RVEF'];
const open = (item: string): ValueChip => ({ item, state: 'open', value: null, quote: null });

describe('value cluster chips', () => {
	it('start open, in the template order', () => {
		expect(initialChips(ITEMS)).toEqual(ITEMS.map(open));
		expect(blockingValues(initialChips(ITEMS))).toEqual(ITEMS);
	});

	it('a fill sets filled and open chips; the radiologist\'s entries and N/A marks stand', () => {
		let c = enterValue(initialChips(ITEMS), 'LVEDVi', '98 mL/m²');
		c = markNa(c, 'RVEF');
		c = mergeFill(c, [
			{ item: 'lvef', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'LVEDVi', state: 'filled', value: '90', quote: 'LVEDVi 90.' },
			{ item: 'RVEF', state: 'open', value: null, quote: null }
		]);
		expect(c).toEqual([
			{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'LVEDVi', state: 'entered', value: '98 mL/m²', quote: null },
			{ item: 'RVEF', state: 'na', value: null, quote: null }
		]);
		expect(blockingValues(c)).toEqual([]);
		expect(mergeFill(c, [])[0]).toEqual(open('LVEF')); // a filled chip the next fill does not confirm opens again
	});

	it('stated with no sentence named needs a look; once kept it stays kept', () => {
		let c = mergeFill(initialChips(['Conus level']), [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		expect(c[0]).toEqual({ item: 'Conus level', state: 'check', value: null, quote: null });
		expect(blockingValues(c)).toEqual(['Conus level']);
		c = keepStated(c, 'Conus level');
		expect(c[0]).toEqual({ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true });
		expect(blockingValues(c)).toEqual([]);
		c = mergeFill(startFill(c), [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		expect(c[0].state).toBe('filled');
	});

	it('while a fill runs every chip but the radiologist\'s own is filling; a failed fill opens them', () => {
		let c = markNa(mergeFill(initialChips(ITEMS), [{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' }]), 'RVEF');
		c = startFill(c);
		expect(c.map((x) => x.state)).toEqual(['filling', 'filling', 'na']);
		expect(isFilling(c)).toBe(true);
		expect(chipLabel(c[0])).toBe('LVEF …');
		expect(failFill(c).map((x) => x.state)).toEqual(['open', 'open', 'na']);
		expect(isFilling(failFill(c))).toBe(false);
	});

	it('a failed fill never undoes the radiologist\'s choices: a kept "stated" chip stays kept', () => {
		let c = mergeFill(initialChips(['Conus level', 'LVEF', 'RVEF']), [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		c = markNa(enterValue(keepStated(c, 'Conus level'), 'LVEF', '45%'), 'RVEF');
		const before = c;
		c = failFill(startFill(c));
		expect(c).toEqual(before);
		expect(c[0]).toEqual({ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true });
	});

	it('a value typed while a fill runs stands when the fill lands', () => {
		let c = startFill(initialChips(ITEMS));
		c = enterValue(c, 'LVEF', '50%');
		c = mergeFill(c, [{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' }]);
		expect(c[0]).toEqual({ item: 'LVEF', state: 'entered', value: '50%', quote: null });
		expect(c.slice(1).map((x) => x.state)).toEqual(['open', 'open']);
	});

	it('typing empty reopens a chip; Mark rest N/A closes only the open ones', () => {
		let c = enterValue(initialChips([...ITEMS, 'Conus level']), 'LVEF', ' 45% ');
		expect(c[0]).toEqual({ item: 'LVEF', state: 'entered', value: '45%', quote: null });
		expect(enterValue(c, 'LVEF', '  ')[0]).toEqual(open('LVEF'));
		c = mergeFill(c, [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		c = markRestNa(c);
		expect(c.map((x) => x.state)).toEqual(['entered', 'na', 'na', 'check']); // a stated value is never marked N/A in bulk
	});

	it('Generate states only the values the radiologist typed (Hassan 2026-10-13); N/A items are listed', () => {
		const c: ValueChip[] = [
			{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true },
			{ item: 'LVEDVi', state: 'entered', value: '98 mL/m²', quote: null },
			{ item: 'RVEF', state: 'na', value: null, quote: null },
			open('LV mass index')
		];
		expect(valueStatements(c)).toEqual(['LVEDVi 98 mL/m²']);
		expect(naItems(c)).toEqual(['RVEF']);
		expect(filledItems(c)).toEqual(['LVEF', 'Conus level']); // the post-generation backstop checks these in the report
	});

	it('the Generate body carries the N/A and filled items only when the session has a value cluster', () => {
		const c: ValueChip[] = [
			{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'LVEDVi', state: 'entered', value: '98', quote: null },
			{ item: 'RVEF', state: 'na', value: null, quote: null }
		];
		expect(valuesBody(c)).toEqual({ stack_values_na: ['RVEF'], stack_values_filled: ['LVEF'] });
		expect(valuesBody([])).toEqual({ stack_values_na: [], stack_values_filled: [] });
		expect(valuesBody(undefined)).toEqual({}); // an old gate or no template values: the server keeps today's behaviour
	});

	it('labels each state, and the gate key changes with any chip', () => {
		expect(chipLabel({ item: 'LVEF', state: 'filled', value: '45%', quote: 'q' })).toBe('LVEF 45%');
		expect(chipLabel({ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true })).toBe('Conus level stated');
		expect(chipLabel({ item: 'Conus level', state: 'check', value: null, quote: null })).toBe('Conus level stated?');
		expect(chipLabel({ item: 'LVEDVi', state: 'entered', value: '98', quote: null })).toBe('LVEDVi 98');
		expect(chipLabel({ item: 'RVEF', state: 'na', value: null, quote: null })).toBe('RVEF N/A');
		expect(chipLabel(open('LV mass index'))).toBe('LV mass index —');
		const a = initialChips(ITEMS);
		expect(valuesKey(a)).toBe(valuesKey(initialChips(ITEMS)));
		expect(valuesKey(markNa(a, 'RVEF'))).not.toBe(valuesKey(a));
		expect(valuesKey(startFill(a))).not.toBe(valuesKey(a));
		expect(valuesKey(enterValue(a, 'LVEF', '45'))).not.toBe(valuesKey(enterValue(a, 'LVEF', '46')));
	});
});
