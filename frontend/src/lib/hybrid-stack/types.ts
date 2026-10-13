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
	quiet?: string[];
	protocol?: { id: string; display_name: string; scan_type_line: string; phases: string[]; laterality: string | null } | null;
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
export interface ViewGroup { name: string; rows: ViewRow[]; members: string[] } // members: the regions a joined heading spans
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
	source_text?: string; // the dictated phrase that set a finding check off
	question: string;
	why: string;
	sentences: string[]; // still to be answered (at most 2)
	answered: boolean; // the dictation answered every sentence: the row folds
}
export interface ItemsResult { items: StackItem[]; capped: StackItem[]; contradicted: string[]; cached: boolean; ms: number; error: string | null }
export interface SlimSheet { id: string | null; region_normals: Record<string, string[]>; not_assessable: string; status: string; ready: boolean; level_groups?: Record<string, string[]> }
/** Region -> normals the assumed-normal check dropped, with why. */
export type Dropped = Record<string, { sentence: string; reason: string }[]>;
export interface AssumedResult {
	assumed: Record<string, string[]>;
	/** Region -> assumed normals the dictation may conflict with (also in `assumed`): shown highlighted (review R1). */
	flagged?: Record<string, string[]>;
	/** Region -> normals not assumed, with why: covered | contradicted | removed | rule. */
	dropped?: Dropped;
	/** The session's template context-rule decision (condition -> P(met)); kept and sent back (review R5). */
	rules?: Record<string, number> | null;
	/** The sheet has context rules: Confirm re-asks every one with the dictation. */
	confirm_recheck?: boolean;
	ms: number;
	error: string | null;
}
export interface GateItem { id: string; kind: StackItem['kind']; region: string; question: string; sentences: string[]; answered_by: 'dictation' | 'tap' | 'skip' | 'not_assessed' }
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
	// Every row behind the "N more checks" line at Confirm (over the writer's caps), whatever became of it: a tapped
	// one also appears in `items` (answered_by 'tap') and in capped_tapped; a skipped one also in `items`.
	capped: { region: string; question: string }[];
	capped_opened?: boolean; // the "N more checks" line was opened (E1b)
	capped_tapped?: { region: string; question: string }[]; // rows over the cap answered with a tap
	review_failed?: boolean; // the end-of-dictation review failed: no finding checks were offered
	offered?: Record<string, string[]>; // region normals the sheet offered, before the assumed-normal check
	jev_dropped?: Dropped | null; // what the check dropped, with why (null: the check failed)
	flagged?: Record<string, string[]>; // assumed normals confirmed with the "may conflict" marker (R1)
	assumed_check_failed?: boolean; // the assumed-normal check failed: nothing was dropped by it
	// Dictation checks seen this session and how each ended: answered, skipped, edited away, or still open (advisory).
	checks?: { kind: string; quote: string; other: string | null; answered_by: 'as_dictated' | 'skip' | 'replaced' | 'edited' | 'open' }[];
	units_hash: string;
}
export interface StackCommand { action: 'dictate' | 'delete' | 'answer'; region: string | null; item: string | null; command: string | null; confidence: number | null }
