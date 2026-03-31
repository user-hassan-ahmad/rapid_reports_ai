/** Must stay aligned with backend `AuditFixContext` / `AuditGuidelineRef` in enhancement_models.py */

export const AUDIT_FIX_CRITERIA_SUMMARY_MAX = 600;

export interface AuditGuidelineRefForChat {
	system: string;
	type: string;
	context: string;
	criteria_summary: string | null;
}

export interface AuditFixContext {
	audit_id: string;
	criterion: string;
	rationale: string;
	criterion_line: string | null;
	highlighted_spans: string[];
	suggested_replacement: string | null;
	guideline_references: AuditGuidelineRefForChat[];
}

export function buildAuditFixGuidelineRefs(
	refs: Array<{
		system: string;
		type: string;
		context?: string;
		criteria_summary?: string | null;
	}> | undefined
): AuditGuidelineRefForChat[] {
	if (!refs?.length) return [];
	return refs.map((r) => {
		const raw = r.criteria_summary;
		let criteria_summary: string | null = null;
		if (raw != null && String(raw).trim()) {
			const s = String(raw);
			criteria_summary =
				s.length > AUDIT_FIX_CRITERIA_SUMMARY_MAX
					? s.slice(0, AUDIT_FIX_CRITERIA_SUMMARY_MAX - 12).trimEnd() + '… [truncated]'
					: s;
		}
		return {
			system: r.system,
			type: r.type,
			context: r.context ?? '',
			criteria_summary
		};
	});
}

export function buildAuditFixContext(
	auditId: string | null,
	criterion: {
		criterion: string;
		rationale: string;
		criterion_line?: string | null;
		highlighted_spans?: string[];
		suggested_replacement?: string | null;
	},
	guidelineRefs:
		| Array<{
				system: string;
				type: string;
				context?: string;
				criteria_summary?: string | null;
		  }>
		| undefined
): AuditFixContext {
	return {
		audit_id: auditId ?? '',
		criterion: criterion.criterion,
		rationale: criterion.rationale,
		criterion_line: criterion.criterion_line ?? null,
		highlighted_spans: criterion.highlighted_spans ?? [],
		suggested_replacement: criterion.suggested_replacement ?? null,
		guideline_references: buildAuditFixGuidelineRefs(guidelineRefs)
	};
}
