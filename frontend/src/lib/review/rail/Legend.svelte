<script lang="ts">
	// The rail header's legend (label set "E · meaning", shared with the editor) and the density toggle.
	import { LEGEND } from '../editor/decorations';
	import type { Density } from '../editor/theme';

	let {
		density = $bindable('quiet'),
		onDensity
	}: { density?: Density; onDensity?: (d: Density) => void } = $props();

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

<div class="rv-legend-bar">
	<ul class="rv-legend" data-rv-legend aria-label="Legend">
		{#each LEGEND as entry (entry.key)}
			<li class="rv-legend-{entry.key}">
				<span class="rv-icon" aria-hidden="true">{entry.icon}</span>{entry.label}
			</li>
		{/each}
	</ul>
	<div class="rv-density" role="group" aria-label="Density">
		{#each CHOICES as c (c.value)}
			<button type="button" aria-pressed={density === c.value} onclick={() => choose(c.value)}
				>{c.label}</button
			>
		{/each}
	</div>
</div>

<style>
	.rv-legend-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
		font-size: 0.7rem;
		color: var(--rv-muted);
	}
	.rv-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 10px;
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.rv-legend li {
		display: inline-flex;
		gap: 3px;
		align-items: baseline;
	}
	.rv-icon {
		font-weight: 700;
	}
	.rv-legend-dictated .rv-icon {
		color: var(--rv-text);
	}
	.rv-legend-normal .rv-icon {
		color: var(--rv-green-line);
	}
	.rv-legend-check .rv-icon {
		color: var(--rv-amber-line);
	}
	.rv-legend-removed .rv-icon,
	.rv-legend-excluded .rv-icon {
		color: var(--rv-red-line);
	}
	.rv-legend-option .rv-icon {
		color: var(--rv-blue-line);
	}
	.rv-density {
		display: inline-flex;
		border: 1px solid var(--rv-border);
		border-radius: 9px;
		overflow: hidden;
	}
	.rv-density button {
		font: inherit;
		background: none;
		border: 0;
		padding: 0 7px;
		line-height: 1.7;
		color: var(--rv-muted);
		cursor: pointer;
	}
	.rv-density button[aria-pressed='true'] {
		background: var(--rv-surface-hover);
		color: var(--rv-text);
		font-weight: 600;
		text-decoration: underline;
	}
	.rv-density button:focus-visible {
		outline: 2px solid var(--rv-blue-line);
		outline-offset: -2px;
	}
</style>
