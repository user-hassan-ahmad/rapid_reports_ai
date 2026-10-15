// The faint connector between a finding's numbered marker in the scratchpad and its guideline card in the rail. Pure geometry.
export interface DOMRectLike { left: number; top: number; right: number; bottom: number; width: number; height: number }
type Size = { width: number; height: number };
/** Every ancestor that scrolls or clips (one rect, a list, or none). */
type Panes = DOMRectLike | DOMRectLike[] | null | undefined;

const within = (r: DOMRectLike, box: { left: number; top: number; right: number; bottom: number }) =>
	r.left >= box.left && r.top >= box.top && r.right <= box.right && r.bottom <= box.bottom;

/** An endpoint is visible only when it lies inside the viewport and inside every scroller or clipper above it (the scratchpad pane
 *  for the marker, the card's own clip and the rail list for the card): scrolled out of its pane it is gone even though it is still on screen. */
export function endpointVisible(r: DOMRectLike, scrollers: Panes, viewport: Size): boolean {
	const list = Array.isArray(scrollers) ? scrollers : scrollers ? [scrollers] : [];
	return within(r, { left: 0, top: 0, right: viewport.width, bottom: viewport.height }) && list.every((s) => within(r, s));
}

/** SVG path `d`: a gentle cubic from the scratchpad marker's right edge (vertical middle) to the guideline card's left
 *  edge (vertical middle of its header). It only spans the gutter between the two panes: null when either end is clipped
 *  or the card is not to the right of the marker. `panes`: each end's nearest scrolling ancestor's rect. */
export function connectorPath(card: DOMRectLike, marker: DOMRectLike, viewport: Size, panes: { marker?: Panes; card?: Panes } = {}): string | null {
	if (!endpointVisible(card, panes.card, viewport) || !endpointVisible(marker, panes.marker, viewport)) return null;
	const x1 = marker.right;
	const y1 = marker.top + marker.height / 2;
	const x2 = card.left;
	const y2 = card.top + card.height / 2;
	if (x2 < x1) return null;
	const dx = (x2 - x1) / 2;
	return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}
