/**
 * Raw Text Detection Utility
 *
 * Detects unfilled placeholders directly in raw markdown text without any
 * HTML round-trip. Returns character positions that map directly to
 * CodeMirror 6 document offsets (view.posAtCoords / Decoration.mark ranges).
 *
 * Mirrors the pattern detection of placeholderDetection.ts but operates
 * on the raw string, making positions safe to use as CM6 from/to ranges.
 */

import type { UnfilledItem, UnfilledItems } from '$lib/utils/placeholderDetection';

function getSurroundingContext(
	text: string,
	index: number,
	matchLength: number,
	contextLength = 50
): string {
	const start = Math.max(0, index - contextLength);
	const end = Math.min(text.length, index + matchLength + contextLength);
	return text.substring(start, end).trim();
}

/**
 * Detect unfilled placeholders in raw markdown text.
 * All returned `index` values are character offsets in the original `content`
 * string — directly usable as CodeMirror 6 document positions.
 */
export function detectUnfilledInRawText(content: string): UnfilledItems {
	if (!content) {
		return {
			measurements: [],
			variables: [],
			alternatives: [],
			instructions: [],
			blank_sections: [],
			total: 0
		};
	}

	const items: UnfilledItems = {
		measurements: [],
		variables: [],
		alternatives: [],
		instructions: [],
		blank_sections: [],
		total: 0
	};

	// Measurements: xxx (case-insensitive, word boundaries)
	const measurementRegex = /\bxxx\b/gi;
	let match: RegExpExecArray | null;
	while ((match = measurementRegex.exec(content)) !== null) {
		items.measurements.push({
			type: 'measurement',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(content, match.index, match[0].length)
		});
	}

	// Variables: {VARIABLE_NAME}
	const variableRegex = /\{(\w+)\}/g;
	while ((match = variableRegex.exec(content)) !== null) {
		items.variables.push({
			type: 'variable',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(content, match.index, match[0].length)
		});
	}

	// Alternatives: [option1/option2] (must have brackets, supports hyphens)
	const alternativeRegex = /\[([\w-]+(?:\/[\w-]+)+)\]/g;
	while ((match = alternativeRegex.exec(content)) !== null) {
		items.alternatives.push({
			type: 'alternative',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(content, match.index, match[0].length)
		});
	}

	// Instructions: // lines (excluding //UNFILLED: markers)
	const instructionRegex = /^\/\/\s*(?!UNFILLED:)(.+)$/gm;
	while ((match = instructionRegex.exec(content)) !== null) {
		items.instructions.push({
			type: 'instruction',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(content, match.index, match[0].length)
		});
	}

	// Blank sections: //UNFILLED: SECTION_NAME
	const blankSectionRegex = /(?:^|\n)(\s*\/\/UNFILLED:\s*(.+?))\s*(?:\n|$)/gm;
	while ((match = blankSectionRegex.exec(content)) !== null) {
		// Find the actual start of //UNFILLED: within the full match
		const fullMatch = match[0];
		const markerOffset = fullMatch.indexOf('//UNFILLED:');
		const actualIndex = match.index + markerOffset;
		items.blank_sections.push({
			type: 'blank_section',
			text: match[2].trim(), // Just the section name
			index: actualIndex,
			surroundingContext: getSurroundingContext(content, actualIndex, match[1].trim().length, 100)
		});
	}

	items.total =
		items.measurements.length +
		items.variables.length +
		items.alternatives.length +
		items.instructions.length +
		items.blank_sections.length;

	return items;
}

/**
 * Find the UnfilledItem at a given document position, if any.
 * Used by the CM6 hover handler to identify which item the cursor is over.
 */
export function findItemAtPos(pos: number, items: UnfilledItems): UnfilledItem | null {
	for (const item of items.measurements) {
		if (pos >= item.index && pos <= item.index + item.text.length) return item;
	}
	for (const item of items.variables) {
		if (pos >= item.index && pos <= item.index + item.text.length) return item;
	}
	for (const item of items.alternatives) {
		if (pos >= item.index && pos <= item.index + item.text.length) return item;
	}
	for (const item of items.blank_sections) {
		// Blank sections span the full //UNFILLED: ... line; give a generous range
		const markerText = `//UNFILLED: ${item.text}`;
		if (pos >= item.index && pos <= item.index + markerText.length + 5) return item;
	}
	return null;
}
