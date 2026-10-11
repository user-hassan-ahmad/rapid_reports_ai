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
	chips_stated?: string[];
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
export type ChipState = 'included' | 'optional';
export interface Chip { text: string; state: ChipState }
export interface ChipsResult { chips: Chip[]; cached: boolean; ms: number; error: string | null }
export interface DraftResult { text: string; ms: number; error: string | null }
export interface GateRecord {
	confirmed_at: string;
	conclusion_text: string;
	conclusion_source: 'dictated' | 'draft' | 'draft_edited' | 'typed';
	assumed_normal: string[];
	remainder_normal: string[];
	dictated_normal: { region: string; words: string[] }[];
	included_chips: { region: string; text: string }[]; // not dictated; confirmed in the report
	declined_chips: string[]; // removed by the radiologist: never stated
	units_hash: string;
}
export interface StackCommand { action: 'dictate' | 'delete' | 'accept'; region: string | null; chip: string | null; command: string | null; confidence: number | null }
