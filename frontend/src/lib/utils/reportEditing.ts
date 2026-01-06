import type { UnfilledEdit } from '../stores/unfilledEditor';

/**
 * Apply edits to report content
 * Replaces unfilled placeholders with user-provided values
 * Uses position-based replacement to handle multiple occurrences correctly
 */
export function applyEditsToReport(
	originalReport: string,
	edits: Map<string, UnfilledEdit>
): string {
	if (!originalReport || edits.size === 0) {
		return originalReport;
	}

	let result = originalReport;

	// Convert edits to array and sort by position (reverse order to preserve indices)
	const sortedEdits = Array.from(edits.values())
		.filter(edit => edit.newValue && edit.newValue.trim() !== '' && edit.newValue !== 'keep')
		.sort((a, b) => {
			// Sort by position if available, otherwise by index in map
			const posA = a.position ?? 0;
			const posB = b.position ?? 0;
			return posB - posA; // Reverse order
		});


	// Apply edits from end to start to preserve positions
	for (const edit of sortedEdits) {
		const escapedText = edit.originalText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		
		
		// For alternatives, replace the full bracketed pattern [option1/option2] with selected value
		if (edit.type === 'alternative') {
			// edit.originalText should be "[option1/option2]", edit.newValue should be "option1" or "option2" (no brackets)
			// Escape brackets for regex
			const escapedBracketed = edit.originalText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
			// Replace first occurrence near position if available
			if (edit.position !== undefined && edit.position > 0) {
				const beforePos = result.substring(0, edit.position);
				const afterPos = result.substring(edit.position);
				const matchIndex = afterPos.indexOf(edit.originalText);
				if (matchIndex !== -1) {
					const actualPos = edit.position + matchIndex;
					result = result.substring(0, actualPos) + edit.newValue + result.substring(actualPos + edit.originalText.length);
				}
			} else {
				// Replace first occurrence
				result = result.replace(edit.originalText, edit.newValue);
			}
		} else if (edit.type === 'measurement') {
			// Replace xxx with value (case insensitive, word boundaries)
			if (edit.position !== undefined && edit.position > 0) {
				const beforePos = result.substring(0, edit.position);
				const afterPos = result.substring(edit.position);
				const matchIndex = afterPos.search(new RegExp(`\\b${escapedText}\\b`, 'i'));
				if (matchIndex !== -1) {
					const actualPos = edit.position + matchIndex;
					result = result.substring(0, actualPos) + edit.newValue + result.substring(actualPos + edit.originalText.length);
				} else {
					// Replace first occurrence
					result = result.replace(new RegExp(`\\b${escapedText}\\b`, 'i'), edit.newValue);
				}
			} else {
				// Replace first occurrence
				result = result.replace(new RegExp(`\\b${escapedText}\\b`, 'i'), edit.newValue);
			}
		} else if (edit.type === 'variable') {
			// Replace {VAR} with value (changed from ~VAR~)
			if (edit.position !== undefined && edit.position > 0) {
				const beforePos = result.substring(0, edit.position);
				const afterPos = result.substring(edit.position);
				const matchIndex = afterPos.indexOf(edit.originalText);
				if (matchIndex !== -1) {
					const actualPos = edit.position + matchIndex;
					result = result.substring(0, actualPos) + edit.newValue + result.substring(actualPos + edit.originalText.length);
				} else {
					// Replace first occurrence
					result = result.replace(edit.originalText, edit.newValue);
				}
			} else {
				// Replace first occurrence
				result = result.replace(edit.originalText, edit.newValue);
			}
		} else if (edit.type === 'instruction') {
			// Remove instruction marker if user confirmed removal
			if (edit.newValue === 'remove' || edit.newValue === '') {
				const regex = new RegExp(escapedText, 'g');
				// Remove first occurrence near position if available
				if (edit.position !== undefined && edit.position > 0) {
					const beforePos = result.substring(0, edit.position);
					const afterPos = result.substring(edit.position);
					const matchIndex = afterPos.indexOf(edit.originalText);
					if (matchIndex !== -1) {
						const actualPos = edit.position + matchIndex;
						result = result.substring(0, actualPos) + result.substring(actualPos + edit.originalText.length);
					}
				} else {
					result = result.replace(regex, '');
				}
			} else if (edit.newValue !== 'keep') {
				// Replace with user's text
				if (edit.position !== undefined && edit.position > 0) {
					const beforePos = result.substring(0, edit.position);
					const afterPos = result.substring(edit.position);
					const matchIndex = afterPos.indexOf(edit.originalText);
					if (matchIndex !== -1) {
						const actualPos = edit.position + matchIndex;
						result = result.substring(0, actualPos) + edit.newValue + result.substring(actualPos + edit.originalText.length);
					}
				} else {
					result = result.replace(edit.originalText, edit.newValue);
				}
			}
		}
	}

	
	return result;
}

/**
 * Generate a unique ID for an unfilled item
 */
export function generateItemId(item: { type: string; index: number; text: string }, typeIndex: number): string {
	return `${item.type}-${typeIndex}-${item.index}-${item.text.substring(0, 10)}`;
}

/**
 * Extract unit from original text using forward lookup from placeholder position
 * Pattern: xxx UNIT or xxx NUMBER UNIT (unit always follows xxx if present)
 * This is more accurate than using surrounding context which can include other measurements
 */
export function extractUnit(originalText: string, placeholderIndex: number, placeholderText: string = 'xxx'): string {
	if (!originalText || placeholderIndex < 0 || placeholderIndex >= originalText.length) return '';
	
	// Normalize text: convert superscripts and carets
	const normalizedText = originalText
		.replace(/[²³⁴]/g, (match) => {
			const map: { [key: string]: string } = { '²': '2', '³': '3', '⁴': '4' };
			return map[match] || match;
		})
		.replace(/\^(\d)/g, '$1');
	
	// Find the placeholder position in normalized text (account for normalization changes)
	// For simplicity, search forward from the original index
	const searchStart = Math.max(0, placeholderIndex - 10);
	const searchEnd = Math.min(normalizedText.length, placeholderIndex + 100);
	const searchText = normalizedText.substring(searchStart, searchEnd);
	const relativeIndex = placeholderIndex - searchStart;
	
	// Find placeholder in search text (handle markdown formatting: **xxx**, *xxx*, xxx)
	const placeholderPattern = placeholderText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // Escape regex chars
	const placeholderRegex = new RegExp(`\\*{0,4}\\b${placeholderPattern}\\b\\*{0,4}`, 'i');
	const placeholderMatch = searchText.substring(relativeIndex).match(placeholderRegex);
	
	if (!placeholderMatch) {
		return '';
	}
	
	// Get text after placeholder (forward lookup)
	const afterPlaceholder = searchText.substring(relativeIndex + placeholderMatch.index + placeholderMatch[0].length);
	
	// Skip whitespace and markdown formatting
	const cleaned = afterPlaceholder.replace(/^\s*\*{0,4}\s*/, '');
	
	// Pattern 1: Complex unit with slash (e.g., "m/s", "g/m2", "ml/m2")
	const complexUnitMatch = cleaned.match(/^([a-z]+\/[a-z0-9²³⁴]+)/i);
	if (complexUnitMatch) {
		const unit = complexUnitMatch[1].toLowerCase();
		return unit;
	}
	
	// Pattern 2: mmHg (special case - can be "mmHg", "mm Hg", "mmhg")
	const mmhgMatch = cleaned.match(/^mm\s*hg/i);
	if (mmhgMatch) {
		return 'mmHg';
	}
	
	// Pattern 3: Simple unit (single word, e.g., "ml", "g", "kg", "cm")
	// Also handle cases like "xxx 50 ml" where there's a number between
	const simpleUnitMatch = cleaned.match(/^(?:\d+\.?\d*\s*)?([a-z]+)(?:\s|$|,|\.|;|\))/i);
	if (simpleUnitMatch) {
		const unit = simpleUnitMatch[1].toLowerCase();
		// Normalize mmHg variations
		if (unit === 'mmhg' || unit === 'mm') {
			// Check if next chars are "hg"
			const nextChars = cleaned.substring(simpleUnitMatch.index + simpleUnitMatch[0].length).trim();
			if (nextChars.startsWith('hg')) {
				return 'mmHg';
			}
		}
		if (unit.length <= 15 && /^[a-z]+$/i.test(unit)) {
			return unit;
		}
	}
	
	return '';
}

/**
 * Legacy overload: Extract unit from context (backward compatibility)
 * @deprecated Use extractUnit(originalText, placeholderIndex, placeholderText) instead
 */
export function extractUnitFromContext(context: string | undefined | null): string {
	if (!context) return '';
	// Try to find placeholder in context and use forward lookup
	const placeholderMatch = context.match(/\b(xxx|\{[^}]+\})/i);
	if (placeholderMatch && placeholderMatch.index !== undefined) {
		return extractUnit(context, placeholderMatch.index, placeholderMatch[1]);
	}
	return '';
}

/**
 * Parse alternatives from text (e.g., "[Normal/increased]" -> ["Normal", "increased"])
 * Handles bracketed alternatives by removing brackets first
 */
export function parseAlternatives(text: string): string[] {
	// Remove brackets if present
	const cleaned = text.replace(/^\[|\]$/g, '');
	return cleaned.split('/').map(opt => opt.trim()).filter(opt => opt.length > 0);
}

