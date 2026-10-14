// mountCopilot (A7 fix round 1): a session started after a clear sends nothing. SYNTHETIC units; fake api.
import { describe, expect, it, vi } from 'vitest';
import type { StackUnit } from '$lib/hybrid-stack/types';
import { mountCopilot } from './mount';
import type { CopilotApi } from './session';

const unit = (id: number, text: string): StackUnit => ({
	id, text, group: 'Lungs', structure: null, attach_to: null, parts: null, covers: [], abnormal: true, pinned: false, heading: false
});
const fakeApi = () => ({ match: vi.fn(() => new Promise(() => {})), matchOther: vi.fn(), open: vi.fn() }) as unknown as CopilotApi & { match: ReturnType<typeof vi.fn> };
const ctx = { scanType: 'CT chest', history: '' };

describe('mountCopilot', () => {
	it('started empty (the scratchpad clear path) it makes no /match call', () => {
		const api = fakeApi();
		const s = mountCopilot(ctx, [], false, ['Lungs'], api);
		expect(api.match).not.toHaveBeenCalled();
		s.destroy();
	});

	it('started on placed units it matches them once, with the context already set', () => {
		const api = fakeApi();
		const s = mountCopilot(ctx, [unit(1, 'a 6 mm solid nodule')], false, ['Lungs'], api);
		expect(api.match).toHaveBeenCalledOnce();
		expect(api.match.mock.calls[0][0]).toMatchObject({ scan_type: 'CT chest', findings: [{ id: 'u1', text: 'a 6 mm solid nodule' }], groups: ['Lungs'] });
		expect(api.match.mock.calls[0][0]).not.toHaveProperty('dictation');
		s.destroy();
	});
});
