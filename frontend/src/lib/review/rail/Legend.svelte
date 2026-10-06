<script lang="ts">
	// The review legend (label set "icon · meaning", shared with the editor marks). In the app it is a slim bar
	// directly under the "Report Editor" title (ReportResponseViewer); it is not part of the rail. The density
	// toggle is a dev-page capability only (`showDensity`): the app's density is fixed to Quiet.
	import { LEGEND } from '../editor/decorations';
	import type { Density } from '../editor/theme';

	let {
		density = $bindable('quiet'),
		onDensity,
		showDensity = false
	}: { density?: Density; onDensity?: (d: Density) => void; showDensity?: boolean } = $props();

	const CHOICES: { value: Density; label: string }[] = [
		{ value: 'full', label: 'Full' },
		{ value: 'quiet', label: 'Quiet' },
		{ value: 'hidden', label: 'Hidden' }
	];

	function choose(d: Density) {
		density = d;
		onDensity?.(d);
	}
</script>

<div class="rv-legend-bar" data-testid="review-legend">
	<ul class="rv-legend" data-rv-legend aria-label="Legend">
		{#each LEGEND as entry (entry.key)}
			<li class="rv-legend-{entry.key}" title={entry.title}>
				<span class="rv-legend-icon" aria-hidden="true">{entry.icon}</span><span>{entry.label}</span>
			</li>
		{/each}
	</ul>
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
		/* one compact row: never two rows at desktop widths; scrolls sideways when the column is very narrow */
		display: flex;
		flex-wrap: nowrap;
		align-items: center;
		justify-content: space-between;
		gap: 4px 12px;
		min-width: 0;
		max-width: 100%;
		overflow-x: auto;
		scrollbar-width: thin;
		font-size: 11px;
		line-height: 1.4;
		color: var(--lg-muted);
	}
	.rv-legend-bar::-webkit-scrollbar {
		height: 3px;
	}
	.rv-legend {
		display: flex;
		flex-wrap: nowrap;
		flex: none;
		gap: 4px 5px;
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.rv-legend li {
		display: inline-flex;
		gap: 5px;
		align-items: center;
		padding: 1px 7px 1px 3px;
		border-radius: 9999px;
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid rgba(255, 255, 255, 0.08);
		white-space: nowrap;
	}
	.rv-legend-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 15px;
		height: 15px;
		border-radius: 9999px;
		font-size: 10px;
		font-weight: 700;
		background: rgba(255, 255, 255, 0.06);
		color: var(--lg-text);
	}
	.rv-legend-normal .rv-legend-icon {
		color: var(--lg-green);
		background: rgba(92, 194, 133, 0.12);
	}
	.rv-legend-check .rv-legend-icon {
		color: var(--lg-amber);
		background: rgba(227, 169, 74, 0.12);
	}
	.rv-legend-removed .rv-legend-icon,
	.rv-legend-excluded .rv-legend-icon {
		color: var(--lg-red);
		background: rgba(255, 122, 122, 0.12);
	}
	.rv-legend-option .rv-legend-icon {
		color: var(--lg-blue);
		background: rgba(126, 166, 240, 0.12);
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
