/**
 * Placeholder Detection Utility
 * 
 * Detects unfilled placeholders in generated reports:
 * - Measurements: xxx (case insensitive)
 * - Variables: ~VARIABLE~
 * - Alternatives: word1/word2 (excluding units)
 * - Instructions: [text]
 */

export interface UnfilledItem {
	type: 'measurement' | 'variable' | 'alternative' | 'instruction' | 'blank_section';
	text: string;
	index: number;
	surroundingContext: string;
}

export interface UnfilledItems {
	measurements: UnfilledItem[];
	variables: UnfilledItem[];
	alternatives: UnfilledItem[];
	instructions: UnfilledItem[];
	blank_sections: UnfilledItem[];
	total: number;
}

// Common unit patterns for medical/radiology measurements
const UNIT_PATTERNS = [
	'ml/m2', 'ml/m²', 'ml/m^2',
	'm/s', 'm/sec',
	'mmhg', 'mm hg',
	'cm2', 'cm²', 'cm^2',
	'mm2', 'mm²', 'mm^2',
	'cm3', 'cm³', 'cm^3',
	'kg/m2', 'kg/m²', 'kg/m^2',
	'g/m2', 'g/m²', 'g/m^2',
	'ml/min', 'ml/minute',
	'mm/s', 'mm/sec',
	'l/min', 'l/minute',
	'bpm', 'beats/min'
];

/**
 * Normalize text by converting superscripts and carets to plain numbers
 */
function normalizeUnit(text: string): string {
	return text
		.toLowerCase()
		.replace(/[²³⁴]/g, (match) => {
			const map: { [key: string]: string } = { '²': '2', '³': '3', '⁴': '4' };
			return map[match] || match;
		})
		.replace(/\^(\d)/g, '$1') // Convert ^2 to 2
		.replace(/\s+/g, ''); // Remove spaces
}

/**
 * Check if a text pattern is a medical unit
 */
function isUnit(text: string): boolean {
	const normalized = normalizeUnit(text);
	
	// Check against known patterns
	if (UNIT_PATTERNS.some(unit => normalizeUnit(unit) === normalized)) {
		return true;
	}
	
	// Pattern-based detection for common unit formats
	// Format: number/letter + letter/number (e.g., ml/m2, kg/m2, g/m2)
	const unitPattern = /^[a-z]+\/[a-z]+\d*$/;
	if (unitPattern.test(normalized)) {
		// Check if it contains common measurement unit prefixes
		const unitPrefixes = ['ml', 'l', 'm', 'mm', 'cm', 'kg', 'g', 'mg', 'bpm'];
		if (unitPrefixes.some(prefix => normalized.startsWith(prefix) || normalized.includes('/' + prefix))) {
			return true;
		}
	}
	
	return false;
}

/**
 * Strip non-prose content (code blocks, URLs, etc.) from HTML
 * Returns text content suitable for placeholder detection
 */
function stripNonProseContent(html: string): string {
	// Create a temporary DOM element to parse HTML
	const temp = document.createElement('div');
	temp.innerHTML = html;
	
	// Remove code blocks and pre-formatted text
	const codeBlocks = temp.querySelectorAll('pre, code');
	codeBlocks.forEach(el => el.remove());
	
	// Get text content (this removes HTML tags)
	let text = temp.textContent || temp.innerText || '';
	
	// Remove URLs (basic pattern)
	text = text.replace(/https?:\/\/[^\s]+/gi, '');
	
	// Remove email addresses
	text = text.replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, '');
	
	return text;
}

/**
 * Extract surrounding context for a match
 */
function getSurroundingContext(text: string, index: number, matchLength: number, contextLength: number = 50): string {
	const start = Math.max(0, index - contextLength);
	const end = Math.min(text.length, index + matchLength + contextLength);
	const context = text.substring(start, end).trim();
	return context;
}

/**
 * Detect unfilled placeholders in report content
 */
export function detectUnfilledPlaceholders(content: string): UnfilledItems {
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
	
	// First render markdown to HTML to handle markdown formatting
	const temp = document.createElement('div');
	temp.innerHTML = content;
	
	// Get plain text for detection (but preserve structure)
	const text = stripNonProseContent(content);
	
	const items: UnfilledItems = {
		measurements: [],
		variables: [],
		alternatives: [],
		instructions: [],
		blank_sections: [],
		total: 0
	};
	
	// Detect measurements: xxx (case insensitive, word boundaries)
	const measurementRegex = /\bxxx\b/gi;
	let match;
	let measurementIndex = 0;
	while ((match = measurementRegex.exec(text)) !== null) {
		const context = getSurroundingContext(text, match.index, match[0].length);
		items.measurements.push({
			type: 'measurement',
			text: match[0],
			index: match.index,
			surroundingContext: context
		});
		measurementIndex++;
	}
	
	// Detect variables: {VAR} (changed from ~VAR~)
	const variableRegex = /\{(\w+)\}/g;
	while ((match = variableRegex.exec(text)) !== null) {
		items.variables.push({
			type: 'variable',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(text, match.index, match[0].length)
		});
	}
	
	// Detect alternatives: [option1/option2] (must have brackets, support hyphens)
	const alternativeRegex = /\[([\w-]+(?:\/[\w-]+)+)\]/g;
	while ((match = alternativeRegex.exec(text)) !== null) {
		items.alternatives.push({
			type: 'alternative',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(text, match.index, match[0].length)
		});
	}
	
	// Detect instructions: // lines (for validation - these should be stripped)
	const instructionRegex = /^\/\/\s*(?!UNFILLED:)(.+)$/gm;
	while ((match = instructionRegex.exec(text)) !== null) {
		items.instructions.push({
			type: 'instruction',
			text: match[0],
			index: match.index,
			surroundingContext: getSurroundingContext(text, match.index, match[0].length)
		});
	}
	
	// Detect blank sections: //UNFILLED: SECTION_NAME (NEW)
	// Match //UNFILLED: at start of line OR preceded by whitespace/newline
	const blankSectionRegex = /(?:^|\n)\s*\/\/UNFILLED:\s*(.+?)(?:\n|$)/gm;
	while ((match = blankSectionRegex.exec(text)) !== null) {
		// Adjust index to account for the leading newline/whitespace in the match
		const actualIndex = match.index + (match[0].match(/^(?:\n)?\s*/)?.[0]?.length || 0);
		const surroundingContext = getSurroundingContext(text, actualIndex, match[0].length, 100);
		items.blank_sections.push({
			type: 'blank_section',
			text: match[1].trim(),  // Just the section name
			index: actualIndex,
			surroundingContext: surroundingContext
		});
	}
	
	items.total = items.measurements.length + items.variables.length + 
	              items.alternatives.length + items.instructions.length +
	              items.blank_sections.length;
	
	return items;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text: string): string {
	const div = document.createElement('div');
	div.textContent = text;
	return div.innerHTML;
}

/**
 * Check if a position in HTML string is inside a tag
 */
function isInsideTag(html: string, position: number): boolean {
	const before = html.substring(0, position);
	const lastTagStart = before.lastIndexOf('<');
	const lastTagEnd = before.lastIndexOf('>');
	return lastTagStart > lastTagEnd;
}

/**
 * Check if text is already wrapped in a highlight span
 */
function isAlreadyHighlighted(html: string, position: number, length: number): boolean {
	const before = html.substring(Math.max(0, position - 100), position);
	const after = html.substring(position + length, Math.min(html.length, position + length + 100));
	return before.includes('unfilled-highlight') || before.includes('class="unfilled-');
}

/**
 * Highlight unfilled content in HTML by injecting spans with color classes
 * Finds all matches in HTML directly (not relying on detection positions)
 */
export function highlightUnfilledContent(html: string, items: UnfilledItems): string {
	if (!html || items.total === 0) {
		return html;
	}
	
	let result = html;
	
	// FIRST: Replace //UNFILLED: markers with unique placeholders BEFORE any HTML processing
	// This avoids complex regex matching in HTML
	const blankSectionMarkers: Array<{ marker: string; sectionName: string }> = [];
	if (items.blank_sections.length > 0) {
		items.blank_sections.forEach((section, idx) => {
			const marker = `___BLANK_SECTION_${idx}___`;
			const pattern = new RegExp(`//UNFILLED:\\s*${section.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'g');
			result = result.replace(pattern, marker);
			blankSectionMarkers.push({ marker, sectionName: section.text });
		});
	}
	
	// Strip all // instruction lines (they should not appear in output)
	// Blank section markers are already replaced above
	result = result.replace(/^\/\/\s*.+$/gm, '');
	
	// Highlight measurements: xxx (case insensitive, word boundaries)
	if (items.measurements.length > 0) {
		const regex = /\bxxx\b/gi;
		const matches: Array<{ index: number; match: string; itemIndex: number }> = [];
		let itemIndex = 0;
		
		regex.lastIndex = 0;
		let match;
		while ((match = regex.exec(result)) !== null) {
			if (!isInsideTag(result, match.index) && !isAlreadyHighlighted(result, match.index, match[0].length)) {
				if (itemIndex < items.measurements.length) {
					matches.push({ index: match.index, match: match[0], itemIndex });
					itemIndex++;
				}
			}
		}
		
		// Process in reverse order
		for (let i = matches.length - 1; i >= 0; i--) {
			const { index, match: matchedText, itemIndex: idx } = matches[i];
			const item = items.measurements[idx];
			if (item) {
				const escapedContext = escapeHtml(item.surroundingContext);
				const escapedText = escapeHtml(item.text);
				const replacement = `<span class="unfilled-highlight unfilled-measurement" data-type="measurement" data-text="${escapedText}" data-context="${escapedContext}" data-index="${item.index}">${matchedText}</span>`;
				result = result.substring(0, index) + replacement + result.substring(index + matchedText.length);
			}
		}
	}
	
	// Highlight variables: {VAR} (UPDATED from ~VAR~)
	if (items.variables.length > 0) {
		const regex = /\{(\w+)\}/g;
		const matches: Array<{ index: number; match: string; itemIndex: number }> = [];
		
		regex.lastIndex = 0;
		let match;
		while ((match = regex.exec(result)) !== null) {
			if (!isInsideTag(result, match.index) && !isAlreadyHighlighted(result, match.index, match[0].length)) {
				// Find matching variable item
				const matchingItem = items.variables.find(v => v.text === match[0]);
				if (matchingItem) {
					const idx = items.variables.indexOf(matchingItem);
					matches.push({ index: match.index, match: match[0], itemIndex: idx });
				}
			}
		}
		
		// Process in reverse order
		for (let i = matches.length - 1; i >= 0; i--) {
			const { index, match: matchedText, itemIndex: idx } = matches[i];
			const item = items.variables[idx];
			if (item) {
				const escapedVar = escapeHtml(matchedText);
				const escapedContext = escapeHtml(item.surroundingContext);
				const replacement = `<span class="unfilled-highlight unfilled-variable" data-type="variable" data-text="${escapedVar}" data-context="${escapedContext}" data-index="${item.index}">${matchedText}</span>`;
				result = result.substring(0, index) + replacement + result.substring(index + matchedText.length);
			}
		}
	}
	
	// Highlight alternatives: [option1/option2] (UPDATED to require brackets)
	if (items.alternatives.length > 0) {
		const regex = /\[([\w-]+(?:\/[\w-]+)+)\]/g;
		const matches: Array<{ index: number; match: string; itemIndex: number }> = [];
		
		regex.lastIndex = 0;
		let match;
		while ((match = regex.exec(result)) !== null) {
			if (!isInsideTag(result, match.index) && !isAlreadyHighlighted(result, match.index, match[0].length)) {
				const matchingItem = items.alternatives.find(alt => 
					alt.text === match[0] || alt.text === match[1]
				);
				if (matchingItem) {
					const idx = items.alternatives.indexOf(matchingItem);
					matches.push({ index: match.index, match: match[0], itemIndex: idx });
				}
			}
		}
		
		// Process in reverse order
		for (let i = matches.length - 1; i >= 0; i--) {
			const { index, match: matchedText, itemIndex: idx } = matches[i];
			const item = items.alternatives[idx];
			if (item) {
				const escapedContext = escapeHtml(item.surroundingContext);
				const escapedText = escapeHtml(item.text);
				const replacement = `<span class="unfilled-highlight unfilled-alternative" data-type="alternative" data-text="${escapedText}" data-context="${escapedContext}" data-index="${item.index}">${matchedText}</span>`;
				result = result.substring(0, index) + replacement + result.substring(index + matchedText.length);
			}
		}
	}
	
	// LAST: Replace blank section markers with final HTML (after all other HTML processing)
	// This is simple string replacement - no complex regex needed
	blankSectionMarkers.forEach(({ marker, sectionName }) => {
		const replacement = `<div class="unfilled-section-marker" data-type="blank_section" data-section="${escapeHtml(sectionName)}">
			<span class="unfilled-section-icon">⚠️</span>
			<span class="unfilled-section-text">Section not assessed: ${escapeHtml(sectionName)}</span>
		</div>`;
		result = result.replace(new RegExp(marker, 'g'), replacement);
	});
	
	return result;
}

/**
 * Generate smart chat context prompt for fixing an unfilled item
 */
export function generateChatContext(
	type: 'measurement' | 'variable' | 'alternative' | 'instruction' | 'blank_section',
	text: string,
	surroundingContext: string
): string {
	const context = surroundingContext.length > 0 ? `\n\nContext: "${surroundingContext}"` : '';
	
	switch (type) {
		case 'measurement':
			return `Please help me fill in the measurement "${text}" in this report.${context}\n\nWhat value should replace "${text}" based on the findings?`;
		
		case 'variable':
			return `This variable "${text}" wasn't filled in the report.${context}\n\nPlease help determine the correct value for ${text} based on the clinical findings.`;
		
		case 'alternative':
			// Extract options from bracketed text (e.g., "[normal/increased]" -> "normal/increased")
			const options = text.replace(/[\[\]]/g, '');
			return `This alternative option "${text}" wasn't selected in the report.${context}\n\nPlease help choose the appropriate option from "${options}" based on the findings. Return just the selected option without brackets.`;
		
		case 'instruction':
			return `This instruction marker "${text}" is still present in the report.${context}\n\nPlease help process this instruction appropriately or remove it if no longer needed.`;
		
		case 'blank_section':
			return `Please help me complete the "${text}" section in this report.${context}\n\nThis section was not addressed in the original findings. Please generate appropriate content for this section based on available information, or indicate if it should be omitted.`;
		
		default:
			return `Please help fix this unfilled placeholder: "${text}".${context}`;
	}
}

