// Wire types for /api/canvas/stack/* (backend hybrid_stack). Spec 2026-10-10-hybrid-dictation-stack-design.
export interface Region { name: string; includes: string }
export interface StackPart { text: string; group: string; abnormal?: boolean }
export interface StackUnit {
	id: number;
	text: string;
	group: string | null;
	structure: string | null;
	attach_to: number | null;
	parts: StackPart[] | null;
	covers: string[];
	abnormal?: boolean;
	pinned: boolean;
	heading: boolean;
}
export interface StackSchema {
	regions: Region[];
	groups: string[];
	pills: string[];
	source: string;
	family: string | null;
	key: string;
	provisional: boolean;
}
export interface GroupResult {
	units: StackUnit[];
	new_ids: number[];
	pills: string[];
	gate: Record<string, unknown>[];
	problems: string[];
	timings_ms: Record<string, number>;
	model: string | null;
	error: string | null;
}
export type StackOrder = 'anatomy' | 'dictated';
export interface ViewRow { unitId: number; text: string; structure: string | null; partOf: number | null; pinned: boolean; children: ViewRow[] }
export interface ViewGroup { name: string; rows: ViewRow[] }
export interface StackView { groups: ViewGroup[]; unplaced: ViewRow[] }

/** Scratchpad v2 (spec 2026-10-11). */
export interface RegionStates {
	abnormal: string[]; // in schema order: shown in the scratchpad
	dictatedNormal: { region: string; words: string[] }[]; // solid pills
	assumedNormal: string[]; // dashed pills
	remainder: string[]; // abnormal regions with nothing dictated normal: "Remainder of X: assumed normal"
}
/** Checklist rows (spec 2026-10-11-scratchpad-checklist §2–§4): asked, never assumed. */
export interface StackItem {
	id: string;
	kind: 'finding' | 'referral';
	region: string;
	question: string;
	why: string;
	sentences: string[]; // still to be answered (at most 2)
	answered: boolean; // the dictation answered every sentence: the row folds
}
export interface ItemsResult { items: StackItem[]; capped: StackItem[]; cached: boolean; ms: number; error: string | null }
export interface AssumedResult { assumed: Record<string, string[]>; ms: number; error: string | null }
export interface GateItem { id: string; kind: StackItem['kind']; region: string; question: string; sentences: string[]; answered_by: 'dictation' | 'tap' }
export interface DraftResult { text: string; ms: number; error: string | null }
export interface GateRecord {
	confirmed_at: string;
	conclusion_text: string;
	conclusion_source: 'dictated' | 'draft' | 'draft_edited' | 'typed';
	assumed_normal: string[];
	remainder_normal: string[];
	dictated_normal: { region: string; words: string[] }[];
	items: GateItem[]; // rows answered by dictation or by a tap (tapped sentences are stated)
	assumed: Record<string, string[]>; // region normals confirmed (not dictated)
	removed: string[]; // sentences the radiologist removed: never stated
	capped: { region: string; question: string }[];
	units_hash: string;
}
export interface StackCommand { action: 'dictate' | 'delete' | 'answer'; region: string | null; item: string | null; command: string | null; confidence: number | null }
