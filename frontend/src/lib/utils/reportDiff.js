/**
 * Split a markdown report into logical blocks for per-block diffing.
 * Prefers markdown headings if present, falls back to blank-line paragraphs.
 * @param {string} report
 * @returns {string[]}
 */
export function splitIntoBlocks(report) {
	if (!report) return [];
	if (/^#{1,6}\s/m.test(report)) {
		return report
			.split(/(?=^#{1,6}\s)/m)
			.map((s) => s.trim())
			.filter(Boolean);
	}
	return report
		.split(/\n\s*\n/)
		.map((s) => s.trim())
		.filter(Boolean);
}

/**
 * Stable string hash for use as a Svelte each-key.
 * @param {string} s
 * @returns {string}
 */
export function hash(s) {
	let h = 0;
	for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
	return (h >>> 0).toString(36);
}

/**
 * Compute the per-block diff between two markdown reports.
 * Returns the next report's blocks tagged with `flash` (block text not present
 * in the prior report) plus a summary `badge` string.
 *
 * Badge rules:
 *   - prev empty (first generation): null
 *   - identical: 'no changes'
 *   - >70% blocks changed: 'regenerated'
 *   - otherwise: 'N section[s] changed'
 *
 * @param {string} prev
 * @param {string} next
 * @returns {{ blocks: { id: string, text: string, flash: boolean }[], badge: string | null }}
 */
export function diffReports(prev, next) {
	const nextBlocks = splitIntoBlocks(next);
	const prevBlocks = splitIntoBlocks(prev);
	const prevSet = new Set(prevBlocks);
	const isFirst = !prev;
	const blocks = nextBlocks.map((text, i) => ({
		id: `${i}-${hash(text)}`,
		text,
		flash: !isFirst && !prevSet.has(text)
	}));
	const changedCount = blocks.filter((b) => b.flash).length;

	let badge = null;
	if (isFirst) {
		badge = null;
	} else if (changedCount === 0) {
		badge = 'no changes';
	} else if (nextBlocks.length > 0 && changedCount / nextBlocks.length > 0.7) {
		badge = 'regenerated';
	} else {
		badge = `${changedCount} section${changedCount === 1 ? '' : 's'} changed`;
	}

	return { blocks, badge };
}
