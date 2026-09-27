/**
 * Verbatim and Structured as two views of one scratchpad. The verbatim text is the source
 * of truth; the structured text is derived from it and remembers which verbatim text it
 * was derived from, so switching views never re-polishes (and never loses) either one.
 * Hand edits in Structured are kept until the verbatim text changes; the next rebuild
 * then replaces them (the caller shows a notice).
 *
 * Plan: docs/superpowers/plans/2026-09-27-verbatim-structured-views.md
 */

export interface StructuredState {
	text: string | null; // the structured text on show (null: never built)
	source: string | null; // the verbatim text it was derived from
	edited: boolean; // hand edits since it was built
	building: string | null; // the verbatim text a request is in flight for
}

export const emptyStructured = (): StructuredState => ({ text: null, source: null, edited: false, building: null });

/** Trailing whitespace (a pending line break, a separator) does not change the content. */
const key = (verbatim: string): string => verbatim.replace(/\s+$/, '');

export function isCurrent(s: StructuredState, verbatim: string): boolean {
	return s.text !== null && s.source === key(verbatim);
}

export function shouldBuild(s: StructuredState, verbatim: string, o: { wanted: boolean; busy: boolean }): boolean {
	if (!o.wanted || o.busy || !verbatim.trim()) return false;
	if (isCurrent(s, verbatim)) return false;
	return s.building !== key(verbatim);
}

export function startBuild(s: StructuredState, verbatim: string): StructuredState {
	return { ...s, building: key(verbatim) };
}

/** A build result: null when it failed (the caller clears `building` and the next settle
 *  retries). A result whose verbatim text has since changed is still newer than what is on
 *  show, so it is shown, but it is not current: the next settle rebuilds. */
export function acceptBuild(
	s: StructuredState,
	source: string,
	text: string | null
): { state: StructuredState; replacedEdits: boolean } | null {
	if (text === null) return null;
	const stillBuilding = s.building !== null && s.building !== key(source) ? s.building : null;
	return {
		state: { text, source: key(source), edited: false, building: stillBuilding },
		replacedEdits: s.edited && s.text !== null
	};
}

export function noteEdit(s: StructuredState, text: string): StructuredState {
	return { ...s, text, edited: true };
}
