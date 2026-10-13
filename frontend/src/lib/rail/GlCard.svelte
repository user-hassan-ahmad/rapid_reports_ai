<script lang="ts" module>
	export type GlBadgeVariant = 'v' | 'c' | 'a' | 'r';
</script>

<script lang="ts">
	/**
	 * The guideline card shell: a head (title, right-aligned badge, a one-line hint while collapsed, then the
	 * host's controls and a chevron) over a body that expands. A solid left strip carries `accent`. Used by the
	 * review rail's guidelines panel and every Copilot card.
	 *
	 * Agreed tints (plan Task 0, Q1–Q9 accepted 2026-10-13): purple accent; amber means "needs your answer";
	 * pre-filled values take the amber-soft highlight (`--rv-amber-bg`) on the value only, never the card;
	 * "set by the exam" is a neutral chip; emerald for normals; rose for the radiologist's additions. Badge
	 * variants: `v` violet (grade), `c` cyan (modality), `a` amber, `r` rose.
	 *
	 * `dim` (a pack that does not apply) fades the card and marks it `aria-disabled`; it still opens, so its
	 * reason stays readable.
	 */
	import type { Snippet } from 'svelte';

	let {
		title,
		badge = null,
		hint = null,
		accent = null,
		open = $bindable(false),
		dim = false,
		controls,
		body
	}: {
		title: string;
		badge?: { text: string; variant: GlBadgeVariant } | null;
		/** One line under the title, shown only while collapsed. */
		hint?: string | null;
		/** The left strip and hint colour (a CSS colour). */
		accent?: string | null;
		open?: boolean;
		dim?: boolean;
		/** Buttons in the head; their clicks should stop propagation so they do not toggle the card. */
		controls?: Snippet;
		body?: Snippet;
	} = $props();

	const toggle = () => (open = !open);
</script>

<div
	class="gl-card"
	class:gl-card--dim={dim}
	aria-disabled={dim || undefined}
	style={accent ? `--gl-accent: ${accent}; --gl-action-color: ${accent}` : undefined}
>
	<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
	<div
		class="gl-head {open ? 'gl-head--open' : ''}"
		role="button"
		tabindex="0"
		onclick={toggle}
		onkeydown={(e) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				toggle();
			}
		}}
	>
		<div class="gl-meta">
			<div class="gl-title-row">
				<span class="gl-title">{title}</span>
				{#if badge}
					<span class="gl-grade-badge ch-{badge.variant}">{badge.text}</span>
				{/if}
			</div>
			{#if !open && hint}
				<div class="gl-action-hint">→ {hint}</div>
			{/if}
		</div>
		<div class="gl-controls">
			{@render controls?.()}
			<svg class="gl-chevron {open ? 'open' : ''}" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/></svg>
		</div>
	</div>

	{#if open && body}
		<div class="gl-body">{@render body()}</div>
	{/if}
</div>

<style>
	.gl-card {
		border-radius: 10px;
		border: 1px solid rgba(255,255,255,0.08);
		background: #0d0d14;
		overflow: hidden;
		transition: border-color 0.18s, background 0.18s;
		position: relative;
	}
	/* Left accent strip — solid, always visible */
	.gl-card::before {
		content: '';
		position: absolute;
		left: 0; top: 0; bottom: 0;
		width: 3px;
		background: var(--gl-accent, #8b5cf6);
		border-radius: 10px 0 0 10px;
	}
	.gl-card:hover {
		border-color: rgba(255,255,255,0.13);
		background: #101018;
	}
	.gl-card--dim {
		opacity: 0.6;
	}

	/* ── Collapsed head ── */
	.gl-head {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 10px 11px 10px 15px;
		cursor: pointer;
		user-select: none;
	}
	.gl-head--open { padding-bottom: 9px; }

	.gl-meta { flex: 1; min-width: 0; }

	/* Row 1: title + grade badge */
	.gl-title-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 8px;
	}
	.gl-title {
		flex: 1;
		min-width: 0;
		font-size: 13px;
		font-weight: 600;
		color: #e8e8ec;
		line-height: 1.3;
		letter-spacing: -0.008em;
	}
	/* Grade badge — right-aligned, theme-consistent */
	.gl-grade-badge {
		flex-shrink: 0;
		font-size: 9px;
		font-weight: 700;
		padding: 2px 7px;
		border-radius: 20px;
		letter-spacing: 0.02em;
		white-space: nowrap;
		margin-top: 2px;
	}
	.ch-v { background: rgba(139,92,246,0.12); color: #c4b5fd; border: 1px solid rgba(139,92,246,0.25); }
	.ch-c { background: rgba(6,182,212,0.1);   color: #67e8f9; border: 1px solid rgba(6,182,212,0.22); }
	.ch-a { background: rgba(245,158,11,0.1);  color: #fcd34d; border: 1px solid rgba(245,158,11,0.22); }
	.ch-r { background: rgba(244,63,94,0.1);   color: #fda4af; border: 1px solid rgba(244,63,94,0.22); }

	/* Row 2: colored action hint (collapsed only) — no extra opacity dimming */
	.gl-action-hint {
		margin-top: 4px;
		font-size: 10.5px;
		font-weight: 500;
		line-height: 1.35;
		color: var(--gl-action-color, #a78bfa);
	}

	/* Controls: the host's buttons + chevron */
	.gl-controls {
		display: flex;
		align-items: center;
		gap: 5px;
		flex-shrink: 0;
		padding-top: 2px;
	}
	.gl-chevron { transition: transform 0.2s; color: #52525b; flex-shrink: 0; }
	.gl-chevron.open { transform: rotate(180deg); color: #a1a1aa; }

	/* ── Expanded body ── */
	.gl-body {
		border-top: 1px solid rgba(255,255,255,0.06);
		padding: 10px 12px 12px 15px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-width: 0;
	}
</style>
