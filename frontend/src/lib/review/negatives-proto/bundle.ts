/**
 * Negatives prototype bundle (dev only, /dev/negatives-proto). Produced offline by the review-labs
 * negatives pipeline: a real report from today's quick pipeline, every generated normal/negative
 * classified (memory: default-negatives policy, 2026-10-03/04).
 *
 * Invariant: `report` IS the document. Contradicted negatives (and negatives carrying an undictated
 * number) are already removed from `report` and appear only as `removed` widgets at `anchor`;
 * options are never in `report` either. Copy/export = document text.
 */
export type NegClass = 'default' | 'implicated';

export interface MarkedItem {
	id: string;
	cls: NegClass; // default → green, implicated → amber
	start: number; // offsets into `report`
	end: number;
	text: string;
	pointer?: string; // the dictated finding that implicates it (implicated only)
}

export interface RemovedItem {
	id: string;
	reason: 'contradicted' | 'number'; // red: auto-excluded, restorable
	anchor: number; // offset into `report` where it was removed from
	text: string; // the exact text restore inserts back
	pointer?: string;
}

export interface OptionItem {
	id: string;
	anchor: number; // offset into `report` (end of the sentence it follows)
	text: string; // ghost text; include inserts " " + text at anchor
	reason?: string;
}

export interface NegativesBundle {
	version: 1;
	id8: string;
	scan: string;
	history: string;
	dictation: string;
	report: string;
	marked: MarkedItem[];
	removed: RemovedItem[];
	options: OptionItem[];
}
