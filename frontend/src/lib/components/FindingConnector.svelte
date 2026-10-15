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

	const esc = (s: string) => s.replace(/["\\]/g, '\\$&');
	function measure() {
		frame = 0;
		if (!active || window.innerWidth < minWidth) { d = null; return; }
		const mark = document.querySelector<HTMLElement>(`[data-finding-mark="${esc(active)}"]`);
		const card = document.querySelector<HTMLElement>(`[data-finding-card="${esc(active)}"]`);
		if (!mark || !card) { d = null; return; }
		const head = card.querySelector<HTMLElement>('.cp-group-head') ?? card;
		d = connectorPath(head.getBoundingClientRect(), mark.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight });
	}
	function schedule() { if (!frame) frame = requestAnimationFrame(measure); }

	$effect(() => {
		void active;
		schedule();
		if (!active) return;
		const mo = new MutationObserver(schedule);
		mo.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
		window.addEventListener('scroll', schedule, true);
		window.addEventListener('resize', schedule);
		return () => {
			mo.disconnect();
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
