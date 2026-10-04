// Mirror of the backend review contract (spec §10.1): review_engine/items.py and the GET/POST shapes in
// review_engine/api.py and store.latest_run. Field names match the backend exactly.

export type LaneName = 'coverage' | 'accuracy' | 'additions';
export type ItemLane = LaneName | 'chat';
export type Cls = 'action' | 'minor' | 'info' | 'suppress';
export type ItemStatus = 'open' | 'pre_applied' | 'applied' | 'dismissed' | 'addressed' | 'stale';
export type EngineMode = 'off' | 'shadow' | 'live';
/** What a client may send to the events route (api.USER_COMMANDS). Anything else is a 422. */
export type UserCommand = 'apply' | 'edit' | 'undo' | 'dismiss' | 'restore' | 'view' | 'ask_chat';

export interface Span {
	start: number;
	end: number;
	text: string;
	text_hash?: string | null; // hash of the report the span was made on
}

export interface Edit {
	mode: 'replace' | 'insert' | 'upgrade' | 'remove';
	find?: string | null; // verbatim, occurs once (replace / upgrade / remove)
	replace?: string | null;
	after?: string | null; // insert: verbatim anchor sentence; null = append to the end of `section`
	section?: string | null;
}

/** Live mode's pre-applied edits: where the edit sits in the written text and what it replaced (live.rebase_items). */
export interface UndoInfo {
	final_span: [number, number];
	original_text: string;
}

/** Lane evidence. Open-ended on the backend; the keys the frontend reads are typed. */
export interface ItemEvidence {
	check_reason?: 'uncertain' | 'conflict' | 'number' | string;
	pointer?: string;
	negative?: boolean;
	undo?: UndoInfo;
	original_anchor?: Span;
	also_anchors?: Span[];
	[key: string]: unknown;
}

export interface HistoryEntry {
	at?: string;
	event: string;
	actor?: string;
	text_hash?: string | null;
	detail?: Record<string, unknown>;
	[key: string]: unknown;
}

export interface ReviewItem {
	id: string;
	key: string;
	report_id: string;
	run_id: string;
	lane: ItemLane;
	detectors: string[];
	kind: string;
	cls: Cls;
	section?: string | null;
	anchor?: Span | null;
	label: string;
	reason: string;
	edit?: Edit | null;
	verified?: Record<string, unknown> | null;
	evidence?: ItemEvidence | null;
	probe?: string | null;
	citation?: Record<string, unknown> | null;
	source_line?: string | null;
	status: ItemStatus;
	history: HistoryEntry[];
	engine_version: string;
}

/** store.write_live's result, minus pre_edit_report (latest_run strips it). */
export interface LiveWrite {
	applied: boolean;
	reason?: string; // no_edits | not_found | report_changed | error: ...
	version_id?: string;
	version_number?: number;
	previous_version_id?: string | null;
	before_hash?: string;
	after_hash?: string;
	[key: string]: unknown;
}

/** Lane state: "done" | "failed" | "skipped" once finished; empty while the run is still going. */
export type LaneState = 'done' | 'failed' | 'skipped' | string;

export interface ReviewRun {
	id: string;
	mode: string;
	engine_version: string;
	pathway: string;
	lanes: Record<string, LaneState>;
	timings_ms: Record<string, number>;
	cost: Record<string, unknown>;
	errors: Record<string, string>;
	created_at: string | null;
	live_write?: LiveWrite | null;
}

/** GET /api/reports/{id}/review */
export interface ReviewResponse {
	success: true;
	mode: EngineMode;
	rail: boolean;
	run: ReviewRun | null;
	lanes: Record<string, LaneState>;
	items: ReviewItem[];
}

/** POST /review/probe */
export interface ProbeResponse {
	success: true;
	text_hash: string;
	addressed: string[];
	reprepare: string[];
	new_items: ReviewItem[];
	error?: string | null;
}

/** POST /review/reprepare */
export interface ReprepareResponse {
	success: true;
	text_hash: string;
	items: ReviewItem[];
}

/** POST /review/rerun */
export interface RerunResponse {
	success: true;
	status: 'running';
}
