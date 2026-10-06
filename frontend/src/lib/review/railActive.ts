// Whether a report viewer is showing the review rail (Plan 3 C5), and whether one is expected before it loads.
// The page reads `reviewRailHoldsAside` to leave out the Copilot aside, its peek rail and padding.
//
// - Each viewer claims "active" under its own owner key, so one viewer turning its rail off never clears another's.
// - The engine mode / rail flag of the first GET /review of the session is remembered (module-level, mirrored in
//   sessionStorage), so later report opens know a rail is coming before their own GET returns: the viewer renders the
//   rail slot (skeleton) at once and the page never mounts the Copilot aside meanwhile.
// - Per report, the outcome of its first GET is recorded. Until it is known, the page holds the aside back unless
//   the session already knows there is no rail (first-ever load: no flash either way).
import { derived, writable, type Readable } from 'svelte/store';

const STORAGE_KEY = 'rr_review_rail';

const owners = new Set<object>();
const active = writable(false);

export const reviewRailActive: Readable<boolean> = { subscribe: active.subscribe };

export function setReviewRailActive(owner: object, on: boolean): void {
	if (on) owners.add(owner);
	else owners.delete(owner);
	active.set(owners.size > 0);
}

function readStored(): boolean | null {
	try {
		const v = sessionStorage.getItem(STORAGE_KEY);
		return v === '1' ? true : v === '0' ? false : null;
	} catch {
		return null;
	}
}

/** The session's known rail mode: true (rail), false (no rail) or null (not known yet). */
const expected = writable<boolean | null>(readStored());
export const reviewRailExpected: Readable<boolean | null> = { subscribe: expected.subscribe };

/** Remember the mode a GET /review reported (live with the rail on → true). */
export function rememberRailMode(on: boolean): void {
	expected.set(on);
	try {
		sessionStorage.setItem(STORAGE_KEY, on ? '1' : '0');
	} catch {
		// storage blocked: the module-level value still serves this page
	}
}

/** Per report id: did its first GET /review settle on a rail ('rail') or not ('none', also on an error)? */
const outcomes = writable<Record<string, 'rail' | 'none'>>({});
export const reviewRailOutcomes: Readable<Record<string, 'rail' | 'none'>> = {
	subscribe: outcomes.subscribe
};

export function recordRailOutcome(reportId: string, outcome: 'rail' | 'none'): void {
	outcomes.update((o) => (o[reportId] === outcome ? o : { ...o, [reportId]: outcome }));
}

/** Pure rule: the page keeps the Copilot aside out while a rail is showing, or (before this report's first review
 * GET settles) unless the session already knows there is no rail. */
export function holdsAside(
	isActive: boolean,
	expectedMode: boolean | null,
	outcome: 'rail' | 'none' | undefined
): boolean {
	if (isActive) return true;
	if (outcome !== undefined) return false;
	return expectedMode !== false;
}

/** For the page: hold the aside back for `reportId` (see holdsAside). */
export function reviewRailHoldsAside(reportId: string | null | undefined): Readable<boolean> {
	return derived([active, expected, outcomes], ([a, e, o]) =>
		holdsAside(a, e, reportId ? o[String(reportId)] : 'none')
	);
}

/** Tests only: forget everything this module remembers. */
export function resetRailMemory(): void {
	owners.clear();
	active.set(false);
	expected.set(null);
	outcomes.set({});
	try {
		sessionStorage.removeItem(STORAGE_KEY);
	} catch {
		// ignore
	}
}
