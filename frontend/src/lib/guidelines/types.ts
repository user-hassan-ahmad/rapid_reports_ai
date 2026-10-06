// Guideline entries returned by POST /api/reports/{id}/enhance (Rich Guideline v2). Shared by the Copilot sidebar
// and the review rail's Guidelines tab (lib/review/rail/GuidelinesPanel.svelte).

export type UrgencyTier = 'urgent' | 'soon' | 'routine' | 'watch' | 'none';

export interface SourceLink {
	url: string;
	title?: string;
	snippet?: string;
	domain?: string;
	[key: string]: unknown;
}

export interface RichFollowUpAction {
	modality: string;
	timing: string;
	indication: string;
	urgency: UrgencyTier;
	guideline_source: string;
}

export interface RichClassificationGrade {
	system: string;
	authority: string;
	year?: string;
	grade: string;
	criteria: string;
	management: string;
}

export interface ActionableThreshold {
	parameter: string;
	threshold: string;
	significance: string;
	measurement_tip: string; // legacy field — new field is `context`
	context: string;
}

export interface RichDifferential {
	diagnosis: string;
	key_features: string;
	excluders: string;
	likelihood: string;
}

export interface GuidelineEntry {
	finding_number?: number;
	finding: string;
	finding_short_label?: string;
	urgency_tier?: UrgencyTier;
	clinical_summary?: string;
	uk_authority?: string;
	guideline_refs?: string[];
	follow_up_actions?: RichFollowUpAction[];
	classifications?: RichClassificationGrade[];
	thresholds?: ActionableThreshold[];
	differentials?: RichDifferential[];
	imaging_flags?: string[];
	sources?: SourceLink[];
	// raw evidence (for chat grounding)
	raw_evidence?: unknown[];
	[key: string]: unknown;
}

export interface Finding {
	finding: string;
	[key: string]: unknown;
}

export interface ApplicableGuideline {
	system: string;
	context: string;
	type: string;
}
