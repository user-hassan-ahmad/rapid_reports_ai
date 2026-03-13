<script lang="ts">
	import { fly, fade, slide } from 'svelte/transition';
	import { tick } from 'svelte';
	import type { EditorView } from '@codemirror/view';

	interface IntelliPrompt { question: string; source_text: string; rationale?: string; }

	export let activePrompts: IntelliPrompt[] = [];
	export let editor: EditorView | null = null;
	export let scrollTop: number = 0;
	export let isReviewing: boolean = false;
	export let onHighlight: (text: string) => void = () => {};
	export let onClearHighlight: () => void = () => {};

	const GUTTER_X = 5;       // center-x of anchor dot (within 12px gutter)
	const CARD_LEFT = 20;     // left edge of cards (px from container left)
	const MIN_CARD_GAP = 6;   // minimum gap between adjacent cards
	const CARD_HEIGHT_EST = 46; // initial height estimate for layout

	let containerEl: HTMLDivElement;
	let expandedSet = new Set<string>();

	// anchorY per source_text — computed from editor viewport coords
	let anchorYMap = new Map<string, number>();

	// Actual card heights tracked by ResizeObserver
	let cardHeightMap: Record<string, number> = {};

	// Svelte action: attaches a ResizeObserver to each card div and returns destroy for cleanup
	function attachObserver(el: HTMLElement, key: string) {
		const ro = new ResizeObserver(() => {
			const h = el.getBoundingClientRect().height;
			if (h > 0 && cardHeightMap[key] !== h) {
				cardHeightMap = { ...cardHeightMap, [key]: h };
			}
		});
		ro.observe(el);
		return { destroy() { ro.disconnect(); } };
	}

	// Only include prompts whose source_text is currently found in the document.
	// This means a card naturally fades out the moment its line is deleted,
	// without waiting for the backend to respond with a new list.
	$: sortedAnchored = (() => {
		const withY = activePrompts
			.filter((p) => p.source_text && anchorYMap.has(p.source_text))
			.map((p) => ({ p, y: anchorYMap.get(p.source_text)! }));
		withY.sort((a, b) => a.y - b.y);
		return withY.map((x) => x.p);
	})();

	// Prompts with no source_text are not rendered — the margin callout system requires an anchor.

	function toggleExpand(question: string) {
		expandedSet = expandedSet.has(question)
			? new Set([...expandedSet].filter((q) => q !== question))
			: new Set([...expandedSet, question]);
	}

	async function recomputeAnchors() {
		if (!editor || !containerEl) return;
		const containerRect = containerEl.getBoundingClientRect();
		const doc = editor.state.doc.toString();
		const newMap = new Map<string, number>();
		for (const p of activePrompts) {
			if (!p.source_text) continue;
			const idx = doc.toLowerCase().indexOf(p.source_text.toLowerCase());
			if (idx === -1) continue;
			const coords = editor.coordsAtPos(idx);
			if (!coords) continue;
			// Use vertical center of the line
			newMap.set(p.source_text, coords.top - containerRect.top + (coords.bottom - coords.top) / 2);
		}
		anchorYMap = newMap;
	}

	$: activePrompts, scrollTop, editor, tick().then(recomputeAnchors);

	// Re-run after the CSS open-transition completes (300ms) so cards land correctly
	// even if the container had zero width during the first tick.
	$: if (activePrompts.length > 0) {
		setTimeout(recomputeAnchors, 320);
	}

	// Greedy top-down distribution: keeps cards close to their anchor, pushes down to prevent overlap
	$: cardYMap = (() => {
		const result = new Map<string, number>();
		let prevBottom = 0;
		for (const p of sortedAnchored) {
			const anchorY = anchorYMap.get(p.source_text) ?? 0;
			const cardH = cardHeightMap[p.question] ?? CARD_HEIGHT_EST;
			const idealY = anchorY - cardH / 2;
			const y = Math.max(idealY, prevBottom + MIN_CARD_GAP);
			result.set(p.question, y);
			prevBottom = y + cardH;
		}
		return result;
	})();

	// SVG path from anchor dot to card left edge midpoint
	function connectorPath(anchorY: number, cardY: number, cardH: number): string {
		const ay = anchorY;
		const cy = cardY + cardH / 2;
		const x0 = GUTTER_X;
		const x1 = CARD_LEFT;
		// Cubic bezier: horizontal tangent at both ends for smooth S-curve
		const mx = (x0 + x1) / 2;
		return `M ${x0},${ay} C ${mx},${ay} ${mx},${cy} ${x1},${cy}`;
	}

	// Hovering a prompt (by source_text key)
	let hoveredSource: string | null = null;
	function onEnter(source: string) {
		hoveredSource = source;
		onHighlight(source);
	}
	function onLeave() {
		hoveredSource = null;
		onClearHighlight();
	}
</script>

<div bind:this={containerEl} class="relative h-full overflow-hidden select-none transition-opacity duration-400 {isReviewing ? 'opacity-40' : 'opacity-100'}">

	<!-- SVG layer: connector lines (rendered behind cards) -->
	<svg class="absolute inset-0 w-full h-full pointer-events-none" style="overflow: visible">
		{#each sortedAnchored as prompt (prompt.question)}
			{@const anchorY = anchorYMap.get(prompt.source_text)}
			{@const cardY = cardYMap.get(prompt.question)}
			{@const cardH = cardHeightMap[prompt.question] ?? CARD_HEIGHT_EST}
			{#if anchorY !== undefined && cardY !== undefined}
				<path
					d={connectorPath(anchorY, cardY, cardH)}
					fill="none"
					stroke-width="1"
					stroke-dasharray="2.5 3"
					stroke-linecap="round"
					stroke={hoveredSource === prompt.source_text ? 'rgba(251,191,36,0.55)' : 'rgba(251,191,36,0.22)'}
					style="transition: stroke 150ms ease"
				/>
			{/if}
		{/each}
	</svg>

	<!-- Gutter anchor dots — positioned at exact source line Y -->
	{#each sortedAnchored as prompt (prompt.question)}
		{@const anchorY = anchorYMap.get(prompt.source_text)}
		{#if anchorY !== undefined && anchorY > -8}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div
				class="absolute"
				style="left: {GUTTER_X - 4}px; top: {anchorY - 4}px; z-index: 2"
				onmouseenter={() => onEnter(prompt.source_text)}
				onmouseleave={onLeave}
				onclick={() => toggleExpand(prompt.question)}
				in:fade={{ duration: 200 }}
				out:fade={{ duration: 150 }}
			>
				<div
					class="w-2 h-2 rounded-full transition-all duration-150 cursor-pointer
						{hoveredSource === prompt.source_text
							? 'bg-amber-300 shadow-sm shadow-amber-400/60 scale-125'
							: 'bg-amber-400/60'}"
				></div>
			</div>
		{/if}
	{/each}

	<!-- Distributed cards — positioned by layout algorithm -->
	{#each sortedAnchored as prompt (prompt.question)}
		{@const cardY = cardYMap.get(prompt.question)}
		{@const isExpanded = expandedSet.has(prompt.question)}
		{#if cardY !== undefined && cardY > -50}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div
				class="absolute right-0"
				style="left: {CARD_LEFT}px; top: {cardY}px; z-index: 1"
				use:attachObserver={prompt.question}
				in:fly={{ x: 12, duration: 240 }}
				out:fade={{ duration: 130 }}
				onmouseenter={() => onEnter(prompt.source_text)}
				onmouseleave={onLeave}
			>
				<div
					class="rounded-lg px-2.5 py-2 transition-colors duration-150 cursor-pointer
						{isExpanded
							? 'bg-black/70 border border-amber-400/20 backdrop-blur-sm'
							: hoveredSource === prompt.source_text
								? 'bg-black/65 border border-white/[0.11] backdrop-blur-sm'
								: 'bg-black/55 border border-white/[0.07] backdrop-blur-sm'}"
					onclick={() => prompt.rationale && toggleExpand(prompt.question)}
				>
					<div class="flex items-start gap-1.5">
						<p class="text-[11px] text-amber-200/80 leading-snug flex-1 min-w-0">{prompt.question}</p>
						{#if prompt.rationale}
							<svg
								class="w-3 h-3 text-gray-600 shrink-0 mt-0.5 transition-transform duration-200 {isExpanded ? 'rotate-180' : ''}"
								fill="none" stroke="currentColor" viewBox="0 0 24 24"
							>
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 9l-7 7-7-7" />
							</svg>
						{/if}
					</div>
					{#if isExpanded && prompt.rationale}
						<div transition:slide={{ duration: 220 }}>
							<p class="text-[11px] text-gray-400 leading-relaxed mt-2 pt-2 border-t border-white/[0.06]">
								{prompt.rationale}
							</p>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	{/each}


</div>
