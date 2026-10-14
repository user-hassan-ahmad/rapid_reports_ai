// Template stack session helpers (integration spec §10).

/** The template inputs Generate sends: every value but FINDINGS (the server builds FINDINGS from units + groups). */
export function templateVariables(values: Record<string, string>): Record<string, string> {
	return Object.fromEntries(Object.entries(values ?? {}).filter(([k]) => k !== 'FINDINGS'));
}
