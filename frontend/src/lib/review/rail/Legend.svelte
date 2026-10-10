<script lang="ts">
	// The review legend, directly under the "Report Editor" title (ReportResponseViewer; not part of the rail).
	// "AI highlights [Off | Key | All] ‹ · Removed (contradicts dictation)". The AI highlights control is a three-way
	// segmented radiogroup (editor/aiMode.ts, remembered in localStorage): Key = amber negatives, violet synthesis and
	// the recommendation underline; All = Key plus green normals; Off = no AI tints. `onFilter` gets the emphasis keys
	// (editor/theme.ts `setEmphasis`). Its breakdown swatches expand inline and show only the categories the mode
	// draws. The removed label shows only while the report has such a removal (`showRemoved`). It wraps onto new
	// lines when narrow (never scrolls sideways). The density toggle is a dev-page capability only (`showDensity`):
	// the app's density is fixed to Quiet.
	import { AI_BREAKDOWN, LEGEND } from '../editor/decorations';
	import { AI_MODE_KEYS, AI_MODES, readAiMode, writeAiMode, type AiMode } from '../editor/aiMode';
	import type { Density } from '../editor/theme';

	let {
		density = $bindable('quiet'),
		onDensity,
		showDensity = false,
		mode = $bindable<AiMode>(readAiMode()),
		onFilter,
		showRemoved = false,
		expanded = $bindable(true)
	}: {
		density?: Density;
		onDensity?: (d: Density) => void;
		showDensity?: boolean;
		/** The AI highlights mode. */
		mode?: AiMode;
		/** Called with the emphasis keys of the chosen mode (Key ['ai'], All ['ai','normals'], Off []). */
		onFilter?: (keys: string[]) => void;
		/** The report currently has a removal that contradicts the dictation: show its legend label. */
		showRemoved?: boolean;
		/** The AI breakdown is shown. */
		expanded?: boolean;
	} = $props();

	const ENTRIES = $derived(LEGEND.filter((e) => e.key !== 'removed' || showRemoved));
	const SHOWN: Record<AiMode, string[]> = {
		key: ['negative', 'synthesis', 'recommendation'],
		all: ['negative', 'synthesis', 'recommendation', 'normal'],
		off: []
	};
	const BREAKDOWN = $derived(AI_BREAKDOWN.filter((b) => SHOWN[mode].includes(b.form)));

	const CHOICES: { value: Density; label: string }[] = [
		{ value: 'full', label: 'Full' },
		{ value: 'quiet', label: 'Quiet' },
		{ value: 'hidden', label: 'Hidden' }
	];
	const SWATCH: Record<string, string> = {
		negative: 'var(--lg-amber)',
		synthesis: 'var(--lg-violet)',
		recommendation: 'var(--lg-teal)',
		normal: 'var(--lg-green)'
	};
	const MODE_LABEL: Record<AiMode, string> = { key: 'Key', all: 'All', off: 'Off' };

	function choose(d: Density) {
		density = d;
		onDensity?.(d);
	}

	function pick(m: AiMode) {
		mode = m;
		writeAiMode(m);
		onFilter?.([...AI_MODE_KEYS[m]]);
	}

	/** Arrow keys move the choice (and focus) around the radiogroup, as native radios do. */
	function onKey(e: KeyboardEvent) {
		const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
		if (!step) return;
		e.preventDefault();
		const next = AI_MODES[(AI_MODES.indexOf(mode) + step + AI_MODES.length) % AI_MODES.length];
		pick(next);
		const group = (e.currentTarget as HTMLElement).closest('[role="radiogroup"]');
		queueMicrotask(() => group?.querySelector<HTMLElement>(`[data-rv-mode="${next}"]`)?.focus());
	}
</script>

{#snippet entry(e: (typeof LEGEND)[number])}
	{#if e.toggle}
		<span class="rv-ai-group">
			<span class="rv-legend-label" title={e.title}>{e.label}</span>
			<span
				class="rv-seg"
				role="radiogroup"
				data-rv-filter={e.key}
				aria-label="AI highlights: Off · Key · All"
				title={e.title}
			>
				{#each AI_MODES as m (m)}
					<button
						type="button"
						role="radio"
						data-rv-mode={m}
						aria-checked={mode === m}
						tabindex={mode === m ? 0 : -1}
						onclick={() => pick(m)}
						onkeydown={onKey}>{MODE_LABEL[m]}</button
					>
				{/each}
			</span>
			{#if mode !== 'off'}
				<button
					type="button"
					class="rv-disclose"
					aria-expanded={expanded}
					aria-controls="rv-ai-breakdown"
					aria-label={expanded ? 'Hide AI highlights breakdown' : 'Show AI highlights breakdown'}
					title={expanded ? 'Hide breakdown' : 'Show breakdown'}
					onclick={() => (expanded = !expanded)}><span aria-hidden="true">{expanded ? '‹' : '›'}</span></button
				>
				{#if expanded}
					<span class="rv-breakdown" id="rv-ai-breakdown" data-rv-breakdown role="list" aria-label="AI highlights breakdown">
						{#each BREAKDOWN as b (b.form)}
							<span class="rv-break" role="listitem" data-rv-form={b.form} title={b.title}
								><i class="rv-swatch" style:background-color={SWATCH[b.form]} aria-hidden="true"></i>{b.label}</span
							>
						{/each}
					</span>
				{/if}
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
		{#each ENTRIES as e (e.key)}{@render entry(e)}{/each}
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
		--lg-violet: #b3a1f5;
		--lg-teal: #4fd1c5;
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
	/* the segmented control: one pill, the chosen segment filled (the app's purple, as the density toggle) */
	.rv-seg {
		display: inline-flex;
		align-items: center;
		background: rgba(31, 41, 55, 0.6);
		border-radius: 9999px;
		padding: 2px;
	}
	.rv-seg button {
		font: inherit;
		background: none;
		border: 0;
		border-radius: 9999px;
		padding: 0 8px;
		color: #d1d5db;
		cursor: pointer;
		transition:
			background-color 120ms ease,
			color 120ms ease;
	}
	.rv-seg button:hover {
		color: #fff;
	}
	.rv-seg button[aria-checked='true'] {
		background: #9333ea;
		color: #fff;
		font-weight: 500;
	}
	.rv-seg button:focus-visible {
		outline: 2px solid #a855f7;
		outline-offset: 1px;
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
