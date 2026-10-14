import { describe, expect, it } from 'vitest';
import { stackGenerateBlocked } from './quickFlow';
import type { GateRecord } from './types';

const gate = { units_hash: 'h' } as unknown as GateRecord;
const base = { isRecording: false, loading: false, scratchpad: 'Liver normal.', gate, analyseLoading: true, sectionsDirty: true };

describe('stack mode Generate locks (spec §10: recording, loading, empty findings, the gate — nothing else)', () => {
	it('blocked while recording, loading, empty, or before Confirm', () => {
		expect(stackGenerateBlocked({ ...base, isRecording: true })).toBe(true);
		expect(stackGenerateBlocked({ ...base, loading: true })).toBe(true);
		expect(stackGenerateBlocked({ ...base, scratchpad: '  \n ' })).toBe(true);
		expect(stackGenerateBlocked({ ...base, gate: null })).toBe(true);
	});
	it('unblocked with a gate even while the (legacy) analyser loads or the sections are dirty', () => {
		expect(stackGenerateBlocked(base)).toBe(false);
	});
});
