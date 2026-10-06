<script lang="ts">
	// The review legend, which doubles as the highlight toggles. In the app it sits directly under the "Report Editor"
	// title (ReportResponseViewer); it is not part of the rail. "Dictated · Removed by you | AI-generated ·
	// Recommendations · Removed (contradicts dictation)". Each pill is a toggle (editor/theme.ts `setEmphasis`):
	// "AI-generated" shows the AI-generated layer in its colours (assumed normal green, check amber, synthesis violet;
	// off by default), "Recommendations" their underline (on by default), the others bring their class forward; several
	// may be on. It wraps onto new lines when narrow (never scrolls sideways). The density toggle is a dev-page capability only
	// (`showDensity`): the app's density is fixed to Quiet.
	import { DEFAULT_LEGEND, LEGEND, type LegendKey } from '../editor/decorations';
	import type { Density } from '../editor/theme';

	let {
		density = $bindable('quiet'),
		onDensity,
		showDensity = false,
		active = $bindable<LegendKey[]>([...DEFAULT_LEGEND]),
		onFilter
	}: {
		density?: Density;
		onDensity?: (d: Density) => void;
		showDensity?: boolean;
		/** The pressed filters, in legend order. */
		active?: LegendKey[];
		onFilter?: (keys: LegendKey[]) => void;
	} = $props();

	const OWN = LEGEND.filter((e) => !e.ai);
	const AI = LEGEND.filter((e) => e.ai);

	const CHOICES: { value: Density; label: string }[] = [
		{ value: 'full', label: 'Full' },
		{ value: 'quiet', label: 'Quiet' },
		{ value: 'hidden', label: 'Hidden' }
	];

	function choose(d: Density) {
		density = d;
		onDensity?.(d);
	}

	function toggle(key: LegendKey) {
		const on = new Set(active);
		if (on.has(key)) on.delete(key);
		else on.add(key);
		active = LEGEND.map((e) => e.key).filter((k) => on.has(k));
		onFilter?.(active);
	}
</script>

{#snippet pill(entry: (typeof LEGEND)[number])}
	<button
		type="button"
		class="rv-pill rv-legend-{entry.key}"
		data-rv-filter={entry.key}
		aria-pressed={active.includes(entry.key)}
		title={entry.title}
		onclick={() => toggle(entry.key)}
		>{#if entry.key === 'ai'}<span class="rv-swatches" aria-hidden="true"
				><i class="rv-sw-green"></i><i class="rv-sw-amber"></i><i class="rv-sw-violet"></i></span
			>{:else}<span class="rv-legend-icon" aria-hidden="true">{entry.icon}</span>{/if}<span
			class="rv-legend-label">{entry.label}</span
		></button
	>
{/snippet}

<div class="rv-legend-bar" data-testid="review-legend">
	<div class="rv-legend" data-rv-legend role="group" aria-label="Legend and highlight filters">
		{#each OWN as entry (entry.key)}{@render pill(entry)}{/each}
		<span class="rv-legend-sep" aria-hidden="true"></span>
		{#each AI as entry (entry.key)}{@render pill(entry)}{/each}
	</div>
	{#if showDensity}
		<div class="rv-density" role="group" aria-label="Density">
			{#each CHOICES as c (c.value)}
				<button type="button" aria-pressed={density === c.value} onclick={() => choose(c.value)}
					>{c.label}</button
				>
			{/each}
		</div>
	{/if}
</div>

<style>
	.rv-legend-bar {
		/* the editor marks' dark colours (editor/theme.ts), so the key reads the same as the text */
		--lg-text: #e5e7eb;
		--lg-muted: #9ca3af;
		--lg-green: #5cc285;
		--lg-amber: #e3a94a;
		--lg-red: #ff7a7a;
		--lg-blue: #7ea6f0;
		--lg-grey: #8f969f;
		--lg-violet: #b3a1f5;
		--lg-teal: #5fd3c6;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 4px 12px;
		min-width: 0;
		max-width: 100%;
		font-size: 11px;
		line-height: 1.4;
		color: var(--lg-muted);
	}
	/* wraps onto new lines when narrow; never scrolls sideways */
	.rv-legend {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
		min-width: 0;
		max-width: 100%;
	}
	.rv-pill {
		font: inherit;
		display: inline-flex;
		gap: 4px;
		align-items: center;
		padding: 1px 7px 1px 3px;
		border-radius: 9999px;
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid rgba(255, 255, 255, 0.08);
		color: var(--lg-muted);
		white-space: nowrap;
		cursor: pointer;
		transition:
			background-color 120ms ease,
			border-color 120ms ease,
			color 120ms ease;
	}
	.rv-pill:hover {
		color: var(--lg-text);
		border-color: rgba(255, 255, 255, 0.18);
	}
	.rv-pill[aria-pressed='true'] {
		color: var(--lg-text);
		background: rgba(147, 51, 234, 0.18);
		border-color: rgba(168, 85, 247, 0.55);
	}
	.rv-pill:focus-visible {
		outline: 2px solid #a855f7;
		outline-offset: 1px;
	}
	.rv-legend-sep {
		width: 1px;
		height: 12px;
		margin: 0 3px;
		background: rgba(255, 255, 255, 0.15);
	}
	.rv-swatches {
		display: inline-flex;
		gap: 2px;
		padding-left: 3px;
	}
	.rv-swatches i {
		width: 7px;
		height: 7px;
		border-radius: 9999px;
	}
	.rv-sw-green {
		background: var(--lg-green);
	}
	.rv-sw-amber {
		background: var(--lg-amber);
	}
	.rv-sw-violet {
		background: var(--lg-violet);
	}
	.rv-legend-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 14px;
		height: 14px;
		border-radius: 9999px;
		font-size: 9px;
		font-weight: 700;
		background: rgba(255, 255, 255, 0.06);
		color: var(--lg-text);
	}
	.rv-legend-rec .rv-legend-icon {
		color: var(--lg-teal);
		background: rgba(95, 211, 198, 0.12);
	}
	.rv-legend-removed .rv-legend-icon {
		color: var(--lg-red);
		background: rgba(255, 122, 122, 0.12);
	}
	.rv-legend-excluded .rv-legend-icon {
		color: var(--lg-grey);
		background: rgba(143, 150, 159, 0.14);
	}
	.rv-density {
		display: inline-flex;
		align-items: center;
		background: rgba(31, 41, 55, 0.6);
		border-radius: 0.5rem;
		padding: 2px;
	}
	.rv-density button {
		font: inherit;
		background: none;
		border: 0;
		border-radius: 0.375rem;
		padding: 2px 8px;
		color: #d1d5db;
		cursor: pointer;
	}
	.rv-density button[aria-pressed='true'] {
		background: #9333ea;
		color: #fff;
		font-weight: 500;
	}
	.rv-density button:focus-visible {
		outline: 2px solid #a855f7;
		outline-offset: 1px;
	}
</style>
