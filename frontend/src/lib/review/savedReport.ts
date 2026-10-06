// History "Open" (F2 M6): the saved report is read fresh from GET /api/reports/{id}, never from the cached history
// row (a save in another tab, or the post-check's background write, may have changed it since the list loaded).
import { get } from 'svelte/store';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';

export interface SavedReportFields {
	id: string;
	report_content?: string | null;
	model_used?: string | null;
	candidate_reports?: Array<{ sections?: unknown } | null> | null;
}

/** The report as saved now, merged over `row`; `row` itself when the read fails (offline, or not found). */
export async function fetchSavedReport<T extends SavedReportFields>(row: T): Promise<T> {
	try {
		const headers: Record<string, string> = {};
		const t = get(token);
		if (t) headers.Authorization = `Bearer ${t}`;
		const res = await fetch(`${API_URL}/api/reports/${encodeURIComponent(row.id)}`, { headers });
		if (!res.ok) return row;
		const data = await res.json();
		if (!data?.success || !data.report || String(data.report.id ?? row.id) !== row.id) return row;
		return { ...row, ...data.report };
	} catch {
		return row;
	}
}

/** The report's section names from its saved candidate (artifacts.sections), else null (the viewer falls back to
 * the report's headings). */
export function savedSections(report: SavedReportFields | null | undefined): string[] | null {
	return sectionList(report?.candidate_reports?.[0]?.sections);
}

/** A non-empty list of section names, else null. */
export function sectionList(v: unknown): string[] | null {
	return Array.isArray(v) && v.length && v.every((s) => typeof s === 'string')
		? (v as string[])
		: null;
}
