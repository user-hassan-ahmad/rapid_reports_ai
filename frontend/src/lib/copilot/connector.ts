// The faint connector between a finding's numbered marker in the scratchpad and its guideline card in the rail. Pure geometry.
export interface DOMRectLike { left: number; top: number; right: number; bottom: number; width: number; height: number }
type Size = { width: number; height: number };

const within = (r: DOMRectLike, box: { left: number; top: number; right: number; bottom: number }) =>
	r.left >= box.left && r.top >= box.top && r.right <= box.right && r.bottom <= box.bottom;

/** An endpoint is visible only when it lies inside the viewport and inside its own scroller (the scratchpad pane for the
 *  marker, the rail list for the card): scrolled out of its pane it is gone even though it is still on screen. */
export function endpointVisible(r: DOMRectLike, scroller: DOMRectLike | null | undefined, viewport: Size): boolean {
	return within(r, { left: 0, top: 0, right: viewport.width, bottom: viewport.height }) && (!scroller || within(r, scroller));
}

/** SVG path `d`: a gentle cubic from the scratchpad marker's right edge (vertical middle) to the guideline card's left
 *  edge (vertical middle of its header). It only spans the gutter between the two panes: null when either end is clipped
 *  or the card is not to the right of the marker. `panes`: each end's nearest scrolling ancestor's rect. */
export function connectorPath(card: DOMRectLike, marker: DOMRectLike, viewport: Size, panes: { marker?: DOMRectLike | null; card?: DOMRectLike | null } = {}): string | null {
	if (!endpointVisible(card, panes.card, viewport) || !endpointVisible(marker, panes.marker, viewport)) return null;
	const x1 = marker.right;
	const y1 = marker.top + marker.height / 2;
	const x2 = card.left;
	const y2 = card.top + card.height / 2;
	if (x2 < x1) return null;
	const dx = (x2 - x1) / 2;
	return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}
