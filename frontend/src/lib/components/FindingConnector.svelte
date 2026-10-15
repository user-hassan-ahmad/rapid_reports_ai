<script lang="ts">
	/**
	 * A faint connector (spec: finding markers, 2026-10-15) from the active finding's rail group to its numbered marker
	 * in the scratchpad margin. Fixed overlay owned by the scratchpad: pointer-events none, aria-hidden, no animation.
	 * Drawn only while a finding is active, in the two-pane layout, with both ends in the viewport; recomputed on
	 * scroll (any scroller, capture), resize and DOM changes, throttled to one frame.
	 */
	import { connectorPath } from '$lib/copilot/connector';

	/** `minWidth`: the rail's narrow breakpoint (RailFrame, 1100 px): below it the rail is an overlay, so no connector. */
	let { active, minWidth = 1100 }: { active: string | null; minWidth?: number } = $props();
	let d = $state<string | null>(null);
	let frame = 0;

	/** Every ancestor that scrolls or clips (overflow not visible on either axis), up to the document: the endpoint is
	 *  seen only where all of them overlap (a card clips to its rounded corners AND sits in the rail's scroller). */
	function panesOf(el: HTMLElement): DOMRect[] {
		const out: DOMRect[] = [];
		for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
			const o = getComputedStyle(p);
			if (o.overflowX !== 'visible' || o.overflowY !== 'visible') out.push(p.getBoundingClientRect());
		}
		return out;
	}
	const esc = (s: string) => s.replace(/["\\]/g, '\\$&');
	function measure() {
		frame = 0;
		if (!active || window.innerWidth < minWidth) { d = null; return; }
		const mark = document.querySelector<HTMLElement>(`[data-finding-mark="${esc(active)}"]`);
		const card = document.querySelector<HTMLElement>(`[data-finding-card="${esc(active)}"]`);
		if (!mark || !card) { d = null; return; }
		// the guideline card's header (not the group marker above it): the first card of the group
		const first = card.querySelector<HTMLElement>('.cp-card') ?? card;
		const head = first.querySelector<HTMLElement>('.gl-head') ?? first;
		d = connectorPath(head.getBoundingClientRect(), mark.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight },
			{ marker: panesOf(mark), card: panesOf(head) });
	}
	function schedule() { if (!frame) frame = requestAnimationFrame(measure); }

	$effect(() => {
		void active;
		schedule();
		if (!active) return;
		// Watch the two containers that hold the ends (the scratchpad stack and the rail's card list), never this overlay,
		// and re-attach when either mounts or remounts: a light body observer only checks which containers exist.
		const SEL = '[data-testid="hybrid-stack"], [data-testid="copilot-cards"]';
		let watched: Element[] = [];
		const inner = new MutationObserver(schedule);
		const attach = () => {
			const now = [...document.querySelectorAll(SEL)];
			if (now.length === watched.length && now.every((e, i) => e === watched[i])) return;
			inner.disconnect();
			watched = now;
			for (const el of now) inner.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
			schedule();
		};
		const mo = new MutationObserver(attach);
		mo.observe(document.body, { childList: true, subtree: true });
		attach();
		window.addEventListener('scroll', schedule, true);
		window.addEventListener('resize', schedule);
		return () => {
			mo.disconnect();
			inner.disconnect();
			window.removeEventListener('scroll', schedule, true);
			window.removeEventListener('resize', schedule);
			if (frame) cancelAnimationFrame(frame);
			frame = 0;
		};
	});
</script>

<svg data-testid="finding-connector" aria-hidden="true" class="pointer-events-none fixed inset-0 z-10 h-full w-full" style="pointer-events: none">
	{#if active && d}<path {d} fill="none" stroke="rgb(167 139 250)" stroke-opacity="0.35" stroke-width="1.25" stroke-linecap="round" />{/if}
</svg>
