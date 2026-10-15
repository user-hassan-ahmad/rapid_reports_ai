// The faint connector between a finding's numbered marker in the scratchpad and its group in the rail. Pure geometry.
export interface DOMRectLike { left: number; top: number; right: number; bottom: number; width: number; height: number }

const inside = (r: DOMRectLike, v: { width: number; height: number }) => r.left >= 0 && r.top >= 0 && r.right <= v.width && r.bottom <= v.height;

/** SVG path `d`: a gentle cubic from the rail group's left edge (vertical middle of its header) to the scratchpad
 *  marker's right edge (vertical middle). Null when either rect is not fully in the viewport. */
export function connectorPath(group: DOMRectLike, marker: DOMRectLike, viewport: { width: number; height: number }): string | null {
	if (!inside(group, viewport) || !inside(marker, viewport)) return null;
	const x1 = group.left;
	const y1 = group.top + group.height / 2;
	const x2 = marker.right;
	const y2 = marker.top + marker.height / 2;
	const dx = Math.max(24, Math.abs(x1 - x2) / 2);
	return `M ${x1} ${y1} C ${x1 - dx} ${y1}, ${x2 + dx} ${y2}, ${x2} ${y2}`;
}
