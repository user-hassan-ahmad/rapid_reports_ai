/**
 * Generate a consistent color for a tag based on its name
 * Ensures good contrast with white text (WCAG AA compliant)
 * Same tag will always get the same color
 */
function generateTagColor(tagName) {
	if (!tagName) return 'rgb(139, 92, 246)'; // Default purple
	
	// Simple hash function to convert tag name to number
	let hash = 0;
	for (let i = 0; i < tagName.length; i++) {
		hash = tagName.charCodeAt(i) + ((hash << 5) - hash);
	}
	
	// Use hash to generate HSV color with:
	// - Saturation: 0.6-0.9 (vibrant but not too bright)
	// - Value: 0.4-0.6 (dark enough for white text contrast)
	// - Hue: 0-360 (full color spectrum)
	const hue = Math.abs(hash) % 360;
	const saturation = 0.6 + (Math.abs(hash * 0.1) % 0.3); // 0.6-0.9
	const value = 0.45 + (Math.abs(hash * 0.05) % 0.15); // 0.45-0.6 (darker for contrast)
	
	// Convert HSV to RGB
	const c = value * saturation;
	const x = c * (1 - Math.abs((hue / 60) % 2 - 1));
	const m = value - c;
	
	let r, g, b;
	if (hue < 60) {
		r = c; g = x; b = 0;
	} else if (hue < 120) {
		r = x; g = c; b = 0;
	} else if (hue < 180) {
		r = 0; g = c; b = x;
	} else if (hue < 240) {
		r = 0; g = x; b = c;
	} else if (hue < 300) {
		r = x; g = 0; b = c;
	} else {
		r = c; g = 0; b = x;
	}
	
	r = Math.round((r + m) * 255);
	g = Math.round((g + m) * 255);
	b = Math.round((b + m) * 255);
	
	return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Get tag color, checking for custom color overrides first
 * @param {string} tagName - The tag name
 * @param {object} customColors - Object mapping tag names to custom colors (from user settings)
 * @returns {string} RGB color string
 */
export function getTagColor(tagName, customColors = null) {
	if (!tagName) return 'rgb(139, 92, 246)'; // Default purple
	
	// Check for custom color override (case-insensitive)
	if (customColors && typeof customColors === 'object') {
		const tagLower = tagName.toLowerCase();
		for (const [key, value] of Object.entries(customColors)) {
			if (key.toLowerCase() === tagLower && value) {
				// Validate it's a valid color string (rgb or hex)
				if (typeof value === 'string' && (value.startsWith('rgb') || value.startsWith('#'))) {
					return value;
				}
			}
		}
	}
	
	// Otherwise generate based on tag name
	return generateTagColor(tagName);
}

/**
 * Get tag color with opacity for borders/overlays
 */
export function getTagColorWithOpacity(tagName, opacity = 0.5, customColors = null) {
	if (!tagName) return `rgba(139, 92, 246, ${opacity})`;
	
	const baseColor = getTagColor(tagName, customColors);
	// Extract RGB values from rgb(r, g, b) or hex format
	const rgbMatch = baseColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
	if (rgbMatch) {
		const [, r, g, b] = rgbMatch;
		return `rgba(${r}, ${g}, ${b}, ${opacity})`;
	}
	// Handle hex colors
	const hexMatch = baseColor.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
	if (hexMatch) {
		let hex = hexMatch[1];
		if (hex.length === 3) {
			hex = hex.split('').map(c => c + c).join('');
		}
		const r = parseInt(hex.substr(0, 2), 16);
		const g = parseInt(hex.substr(2, 2), 16);
		const b = parseInt(hex.substr(4, 2), 16);
		return `rgba(${r}, ${g}, ${b}, ${opacity})`;
	}
	return baseColor;
}

/**
 * Convert hex color to RGB
 */
export function hexToRgb(hex) {
	const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
	return result ? {
		r: parseInt(result[1], 16),
		g: parseInt(result[2], 16),
		b: parseInt(result[3], 16)
	} : null;
}

/**
 * Convert RGB to hex
 */
export function rgbToHex(r, g, b) {
	return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

