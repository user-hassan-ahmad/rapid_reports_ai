<script lang="ts">
	/** The verdict pill (B-design): the outcome's action in a span coloured by its action category, with an icon.
	 *  The category's colour comes from the rail tokens, so both themes follow. */
	import Icon, { type IconName } from './Icon.svelte';
	import { categoryColor, type Verdict } from './format';

	/** `text` replaces the pill's words (the quiet exam line shows the grade, its headline). */
	let { verdict, text = null }: { verdict: Verdict; text?: string | null } = $props();
	const words = $derived(text || verdict.pill);
	const icon: Record<Verdict['category'], IconName> = {
		none: 'check',
		surveillance: 'clock',
		workup: 'search',
		refer: 'alert',
		info: 'info',
		not_applicable: 'slash',
		neutral: 'dot',
		open: 'open'
	};
</script>

<span class="cp-pill cp-pill--{verdict.category}" class:cp-pill--tentative={verdict.tentative} style:--cp-cat={categoryColor(verdict.category)} title={words} data-category={verdict.category}>
	<Icon name={icon[verdict.category]} size={12} />
	<span class="cp-pill-text">{words}</span>
</span>

<style>
	.cp-pill {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		max-width: 15rem;
		padding: 3px 9px 3px 7px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 600;
		line-height: 1.3;
		color: var(--cp-cat);
		background: color-mix(in srgb, var(--cp-cat) 14%, transparent);
		border: 1px solid color-mix(in srgb, var(--cp-cat) 38%, transparent);
		white-space: nowrap;
	}
	.cp-pill-text {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	/* nothing decided yet: an outline, no wash */
	.cp-pill--open,
	.cp-pill--info,
	.cp-pill--neutral,
	.cp-pill--not_applicable {
		background: transparent;
		color: var(--rv-muted);
		border-color: var(--rv-border-strong);
	}
	.cp-pill--open {
		border-style: dashed;
	}
	/* the likeliest outcome, not yet reached: its colour, drawn dashed, no wash */
	.cp-pill--tentative {
		background: transparent;
		border-style: dashed;
	}
	/* an outcome without a category yet: readable, but no colour claim */
	.cp-pill--neutral {
		color: var(--rv-text);
	}
</style>
