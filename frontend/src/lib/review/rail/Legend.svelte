<script lang="ts">
	// The review legend, directly under the "Report Editor" title (ReportResponseViewer); not part of the rail.
	// "Dictated · Removed by you | AI-generated ▾ · Removed (contradicts dictation)". Only "AI-generated" is a toggle
	// (editor/theme.ts `setEmphasis`: the AI-generated layer's tints, ON by default; off = plain text); its breakdown
	// (Normals green, Bears on your finding amber, Synthesis violet) expands inline. The other entries are static labels
	// for what the editor draws. It wraps onto new lines when narrow (never scrolls sideways). The density toggle is a
	// dev-page capability only (`showDensity`): the app's density is fixed to Quiet.
	import { AI_BREAKDOWN, DEFAULT_LEGEND, LEGEND, type LegendKey } from '../editor/decorations';
	import type { Density } from '../editor/theme';

	let {
		density = $bindable('quiet'),
		onDensity,
		showDensity = false,
		active = $bindable<LegendKey[]>([...DEFAULT_LEGEND]),
		onFilter,
		expanded = $bindable(true)
	}: {
		density?: Density;
		onDensity?: (d: Density) => void;
		showDensity?: boolean;
		/** The pressed filters, in legend order. */
		active?: LegendKey[];
		onFilter?: (keys: LegendKey[]) => void;
		/** The AI-generated breakdown is shown. */
		expanded?: boolean;
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

{#snippet entry(e: (typeof LEGEND)[number])}
	{#if e.toggle}
		<span class="rv-ai-group">
			<button
				type="button"
				class="rv-pill rv-legend-{e.key}"
				data-rv-filter={e.key}
				aria-pressed={active.includes(e.key)}
				title={e.title}
				onclick={() => toggle(e.key)}
				><span class="rv-swatches" aria-hidden="true"
					><i class="rv-sw-normal"></i><i class="rv-sw-negative"></i><i class="rv-sw-synthesis"></i></span
				><span class="rv-legend-label">{e.label}</span></button
			><button
				type="button"
				class="rv-disclose"
				aria-expanded={expanded}
				aria-controls="rv-ai-breakdown"
				aria-label={expanded ? 'Hide AI-generated breakdown' : 'Show AI-generated breakdown'}
				title={expanded ? 'Hide breakdown' : 'Show breakdown'}
				onclick={() => (expanded = !expanded)}><span aria-hidden="true">{expanded ? '‹' : '›'}</span></button
			>
			{#if expanded}
				<span
					class="rv-breakdown"
					id="rv-ai-breakdown"
					data-rv-breakdown
					data-off={!active.includes(e.key) || undefined}
					role="list"
					aria-label="AI-generated breakdown"
				>
					{#each AI_BREAKDOWN as b (b.form)}
						<span class="rv-break" role="listitem" data-rv-form={b.form} title={b.title}
							><i class="rv-swatch rv-sw-{b.form}" aria-hidden="true"></i>{b.label}</span
						>
					{/each}
				</span>
			{/if}
		</span>
	{:else}
		<span class="rv-tag rv-legend-{e.key}" data-rv-label={e.key} title={e.title}
			><span class="rv-legend-icon" aria-hidden="true">{e.icon}</span><span class="rv-legend-label"
				>{e.label}</span
			></span
		>
	{/if}
{/snippet}

<div class="rv-legend-bar" data-testid="review-legend">
	<div class="rv-legend" data-rv-legend role="group" aria-label="Legend">
		{#each OWN as e (e.key)}{@render entry(e)}{/each}
		<span class="rv-legend-sep" aria-hidden="true"></span>
		{#each AI as e (e.key)}{@render entry(e)}{/each}
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
	/* the editor's tints, stronger so the key reads at 11px */
	.rv-sw-normal {
		background: var(--lg-green);
	}
	.rv-sw-negative {
		background: var(--lg-amber);
	}
	.rv-sw-synthesis {
		background: var(--lg-violet);
	}
	.rv-ai-group {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px 4px;
		min-width: 0;
	}
	.rv-disclose {
		font: inherit;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		padding: 0;
		border: 0;
		border-radius: 4px;
		background: none;
		color: var(--lg-muted);
		cursor: pointer;
	}
	.rv-disclose:hover {
		color: var(--lg-text);
		background: rgba(255, 255, 255, 0.06);
	}
	.rv-disclose:focus-visible {
		outline: 2px solid #a855f7;
		outline-offset: 0;
	}
	.rv-breakdown {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px 8px;
		min-width: 0;
		transition: opacity 120ms ease;
	}
	.rv-breakdown[data-off] {
		opacity: 0.45;
	}
	.rv-break {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		white-space: nowrap;
		color: var(--lg-text);
	}
	.rv-swatch {
		display: inline-block;
		width: 12px;
		height: 10px;
		border-radius: 2px;
		opacity: 0.55;
	}
	.rv-tag {
		display: inline-flex;
		gap: 4px;
		align-items: center;
		padding: 1px 7px 1px 3px;
		color: var(--lg-muted);
		white-space: nowrap;
		cursor: default;
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
