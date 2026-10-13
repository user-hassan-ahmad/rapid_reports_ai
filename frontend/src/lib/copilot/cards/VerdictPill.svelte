<script lang="ts">
	/** The verdict pill (B-design): the outcome's action in a span coloured by its action category, with an icon.
	 *  The category's colour comes from the rail tokens, so both themes follow. */
	import Icon, { type IconName } from './Icon.svelte';
	import { categoryColor, categoryText, type Verdict } from './format';

	/** `text` replaces the pill's words (the quiet exam line shows the grade, its headline). */
	let { verdict, text = null }: { verdict: Verdict; text?: string | null } = $props();
	const words = $derived(text || verdict.pill);
	// a native title only when the text is cut off: otherwise it repeats what is on screen
	let truncated = $state(false);
	const measure = (e: Event) => {
		const t = (e.currentTarget as HTMLElement).querySelector<HTMLElement>('.cp-pill-text');
		truncated = !!t && t.scrollWidth > t.clientWidth + 1;
	};
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

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span
	class="cp-pill cp-pill--{verdict.category}"
	class:cp-pill--tentative={verdict.tentative}
	style:--cp-cat={categoryColor(verdict.category)}
	style:--cp-cat-text={categoryText(verdict.category)}
	title={truncated ? words : undefined}
	data-category={verdict.category}
	onpointerenter={measure}
	onfocusin={measure}
>
	<span class="cp-pill-icon"><Icon name={icon[verdict.category]} size={12} /></span>
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
		color: var(--cp-cat-text);
		background: color-mix(in srgb, var(--cp-cat) 14%, transparent);
		border: 1px solid color-mix(in srgb, var(--cp-cat) 38%, transparent);
		white-space: nowrap;
	}
	.cp-pill-icon {
		display: inline-flex;
		color: var(--cp-cat);
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
