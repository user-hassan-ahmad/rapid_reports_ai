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
	/** The written text of `final_span`, and up to 16 characters of written text either side of it: the client
	 * re-finds the span by this context once the report has changed (anchors.locateUndo). */
	final_text?: string;
	left?: string;
	right?: string;
}

/** Lane evidence. Open-ended on the backend; the keys the frontend reads are typed. */
export interface ItemEvidence {
	check_reason?: 'uncertain' | 'conflict' | 'number' | string;
	pointer?: string;
	negative?: boolean;
	undo?: UndoInfo;
	/** The anchor before live.rebase_items moved or dropped it (a pre-applied insert undone is found by it). */
	original_anchor?: Span;
	/** Removed (red) items: the text taken out, and why ("number" = an undictated measurement). */
	removed_text?: string;
	removal_reason?: 'contradicted' | 'number' | string;
	/** Shadow / kill switch: the engine would have pre-applied this edit in live mode. */
	would_pre_apply?: boolean;
	/** Number checks: the clause the card is about. */
	clause?: string;
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
	/** Client only (never sent by the backend): the last event for this item failed to post after retries. The
	 * local status is kept; the store keeps retrying on the next event. */
	syncError?: string | null;
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
