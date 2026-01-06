/**
 * Syntax highlighting utility for structured template placeholders
 * Supports: {VAR}, xxx, [option1/option2], // instruction
 */

export function highlightSyntax(text: string): string {
	if (!text) return '';
	
	// Escape HTML
	let highlighted = text
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
	
	// Highlight patterns (order matters!)
	highlighted = highlighted
		// Variables: {VAR}
		.replace(/\{(\w+)\}/g, '<span class="highlight-variable">{$1}</span>')
		// Instructions: // instruction
		.replace(/^\/\/\s*(.+)$/gm, '<span class="highlight-instruction">// $1</span>')
		// Measurements: xxx (case insensitive)
		.replace(/\b[xX]{3}\b/g, '<span class="highlight-measurement">$&</span>')
		// Alternatives: [option1/option2] (must have brackets, support hyphens)
		.replace(/\[([\w-]+(?:\/[\w-]+)+)\]/g, '<span class="highlight-alternative">[$1]</span>');
	
	return highlighted;
}

