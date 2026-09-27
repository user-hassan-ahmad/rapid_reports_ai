import { describe, expect, it } from 'vitest';
import { acceptBuild, emptyStructured, isCurrent, noteEdit, shouldBuild, startBuild } from './structuredView';

const V = 'There is a 34 mm mass in the right upper lobe. No pleural effusion.';
const S = '- 34 mm mass in the right upper lobe\n- No pleural effusion';

describe('structured view state', () => {
	it('builds only when wanted, idle, non-empty and not already current or building', () => {
		const s = emptyStructured();
		expect(shouldBuild(s, V, { wanted: false, busy: false })).toBe(false);
		expect(shouldBuild(s, V, { wanted: true, busy: true })).toBe(false);
		expect(shouldBuild(s, '  ', { wanted: true, busy: false })).toBe(false);
		expect(shouldBuild(s, V, { wanted: true, busy: false })).toBe(true);
		const b = startBuild(s, V);
		expect(shouldBuild(b, V, { wanted: true, busy: false })).toBe(false);
	});

	it('is current once a build for the present verbatim text lands (trailing whitespace ignored)', () => {
		const r = acceptBuild(startBuild(emptyStructured(), V), V, S, V + '\n');
		expect(r).not.toBeNull();
		expect(r!.state.text).toBe(S);
		expect(isCurrent(r!.state, V)).toBe(true);
		expect(shouldBuild(r!.state, V, { wanted: true, busy: false })).toBe(false);
	});

	it('discards a build whose verbatim text has since changed', () => {
		const s = startBuild(emptyStructured(), V);
		expect(acceptBuild(s, V, S, V + ' Small hiatus hernia.')).toBeNull();
	});

	it('keeps hand edits while the verbatim text is unchanged', () => {
		const built = acceptBuild(startBuild(emptyStructured(), V), V, S, V)!.state;
		const edited = noteEdit(built, S + '\n- edited by hand');
		expect(edited.edited).toBe(true);
		expect(isCurrent(edited, V)).toBe(true);
		expect(shouldBuild(edited, V, { wanted: true, busy: false })).toBe(false);
	});

	it('replaces hand edits once the verbatim text changes, and says so', () => {
		const built = acceptBuild(startBuild(emptyStructured(), V), V, S, V)!.state;
		const edited = noteEdit(built, S + '\n- edited by hand');
		const V2 = V + ' Small hiatus hernia.';
		expect(shouldBuild(edited, V2, { wanted: true, busy: false })).toBe(true);
		const r = acceptBuild(startBuild(edited, V2), V2, S + '\n- Small hiatus hernia', V2)!;
		expect(r.replacedEdits).toBe(true);
		expect(r.state.edited).toBe(false);
	});

	it('a failed build clears the in-flight marker so the next settle retries', () => {
		const s = startBuild(emptyStructured(), V);
		const r = acceptBuild(s, V, null, V);
		expect(r).toBeNull();
		expect(shouldBuild({ ...s, building: null }, V, { wanted: true, busy: false })).toBe(true);
	});
});
