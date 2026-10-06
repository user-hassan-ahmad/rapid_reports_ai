// Whether a report viewer is showing the review rail (Plan 3 C5). The page reads it to leave out the Copilot aside,
// its peek rail and padding. Each viewer claims it under its own owner key, so one viewer turning its rail off never
// clears another's.
import { writable, type Readable } from 'svelte/store';

const owners = new Set<object>();
const active = writable(false);

export const reviewRailActive: Readable<boolean> = { subscribe: active.subscribe };

export function setReviewRailActive(owner: object, on: boolean): void {
	if (on) owners.add(owner);
	else owners.delete(owner);
	active.set(owners.size > 0);
}
