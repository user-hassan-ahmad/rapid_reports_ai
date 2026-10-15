<script lang="ts">
	/**
	 * One value the card shows (Slice B1, §7.5), read-only until B2:
	 * - read: plain;
	 * - prefilled: the value on the agreed amber-soft highlight (the value only, never the row), plus a "pre-filled"
	 *   chip whose reasons (why[]) are in its tooltip and in the row's description;
	 * - an exam preset (by === 'exam'): the neutral "set by the exam" chip, no highlight (unless it also carries a
	 *   real reason: then both chips, the highlight and the reason);
	 * - answered / edited: as set; not_applicable: "N/A";
	 * - assumed (simplified card): a dashed value with an "assumed" badge and, when the backend says so, whether the
	 *   assumption is decisive (no tag when it does not say: never guessed);
	 * - asked: "not stated", with "Answer" instead of "Change".
	 * Every row carries its provenance badge (read · pre-filled · assumed · set by the exam · answered · changed).
	 * A row with a quote or reasons is focusable (keyboard, or a tap) and shows them in a bubble; screen readers get
	 * them as its description.
	 */
	import { WHY_EXAM, displayValue, type ValueRow } from './format';
	import ValueEdit from './ValueEdit.svelte';

	/** `onEdit` (Slice B2) makes the value changeable: a "Change" button opens ValueEdit in place. N/A never is. */
	/** `doubt`: a pre-filled value that would make the guideline not apply (scope_doubt): highlighted, Change in view. */
	let {
		row,
		uid,
		onEdit = null,
		doubt = false
	}: { row: ValueRow; uid: string; onEdit?: ((input: string, value: string) => void) | null; doubt?: boolean } = $props();
	let editing = $state(false);
	const editable = $derived(!!onEdit && row.state !== 'not_applicable');
	const why = $derived(row.why.filter((w) => w !== WHY_EXAM));
	const prefilled = $derived(row.state === 'prefilled' && (!row.byExam || why.length > 0));
	const reasons = $derived(why.length ? why.join('; ') : 'not read with certainty');
	// every pre-filled row is focusable, so its reasons are reachable without hover
	const described = $derived(!!row.quote || prefilled);
	const descId = $derived(`${uid}-d-${row.input}`);
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<li
	class="cp-val"
	class:cp-val--doubt={doubt}
	data-state={row.state}
	tabindex={described ? 0 : undefined}
	aria-describedby={described ? descId : undefined}
>
	<span class="cp-val-label">{row.label}</span>
	<span class="cp-val-value">
		{#if editing}
			<ValueEdit
				label={row.label}
				value={row.value}
				options={row.options ?? []}
				onSave={(v) => {
					editing = false;
					if (v !== row.value) onEdit?.(row.input, v);
				}}
				onCancel={() => (editing = false)}
			/>
		{:else if row.state === 'not_applicable'}
			<span class="cp-muted">N/A</span>
		{:else if row.state === 'asked'}
			<span class="cp-muted">not stated</span>
		{:else if row.state === 'assumed'}
			<b class="cp-assumed-val">{displayValue(row.value, row.basis)}</b>
		{:else if prefilled}
			<b class="cp-prefill">{displayValue(row.value, row.basis)}</b>
		{:else if row.value}
			<b>{displayValue(row.value, row.basis)}</b>
		{:else}
			<span class="cp-muted">{row.state.replace(/_/g, ' ')}</span>
		{/if}
		<!-- where a derived value came from (e.g. "from the CT of 12 Mar 2025"), so a wrong source can be corrected -->
		{#if row.basis && !editing}<span class="cp-val-basis">{row.basis}</span>{/if}
		{#if !editing && row.state === 'read' && !row.byExam}<span class="cp-chip cp-val-chip cp-chip-read">read</span>{/if}
		{#if !editing && row.state === 'assumed'}
			<span class="cp-chip cp-val-chip cp-chip-warn">{row.sign ? 'assumed absent' : 'assumed'}</span>
			{#if row.decisive === true}<span class="cp-chip cp-val-chip cp-chip-decisive">decisive</span>{/if}
			{#if row.decisive === false}<span class="cp-chip cp-val-chip">doesn't affect outcome</span>{/if}
		{/if}
		{#if !editing && row.state === 'edited'}<span class="cp-chip cp-val-chip">changed</span>{/if}
		{#if !editing && row.state === 'answered'}<span class="cp-chip cp-val-chip">answered</span>{/if}
		{#if row.byExam && !editing}
			<span class="cp-chip cp-val-chip">set by the exam</span>
		{/if}
		{#if prefilled && !row.byExam && !row.basis && !editing}
			<!-- no native title: the row's own bubble shows the reasons (a title showed them twice, Hassan 2026-10-13) -->
			<span class="cp-chip cp-val-chip cp-chip-why">probably from your dictation</span>
		{/if}
		{#if editable && !editing}
			<button
				type="button"
				class="rv-btn rv-btn-ghost cp-val-change"
				aria-label={`${row.state === 'asked' ? 'Answer' : 'Change'} ${row.label}`}
				onclick={(e) => (e.stopPropagation(), (editing = true))}>{row.state === 'asked' ? 'Answer' : 'Change'}</button
			>
		{/if}
	</span>
	{#if described}
		<span class="cp-quote" id={descId}>
			{#if row.quote}<span class="cp-quote-text">“{row.quote}”</span>{/if}
			{#if prefilled}<span class="cp-why">Not verified: {reasons}</span>{/if}
		</span>
	{/if}
</li>

<style>
	.cp-val {
		position: relative;
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 8px;
		padding: 2px 6px;
		margin: 0 -6px;
		border-radius: 4px;
	}
	.cp-val[tabindex]:hover,
	.cp-val[tabindex]:focus {
		background: var(--rv-surface-hover);
		outline: none;
	}
	.cp-val[tabindex]:focus-visible {
		box-shadow: 0 0 0 2px var(--rv-focus);
	}
	.cp-val-label {
		flex: 0 0 44%; /* one column of labels, long ones wrap */
		color: var(--rv-muted);
	}
	.cp-val-value {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 3px 6px;
		font-variant-numeric: tabular-nums;
	}
	/* the value takes the line; its tags wrap onto the line under it */
	.cp-val-value > b,
	.cp-val-value > .cp-muted {
		flex: 0 0 100%;
	}
	.cp-val-basis {
		flex: 0 0 100%;
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.cp-val-value b {
		font-weight: 600;
	}
	/* the agreed amber-soft highlight, on the value only */
	.cp-prefill {
		padding: 0 4px;
		border-radius: 3px;
		background: var(--rv-amber-bg);
	}
	/* tags wrap onto their own line under the value instead of squeezing beside a long label */
	.cp-val-chip {
		display: inline-block;
		max-width: 100%;
		margin-left: 0;
		vertical-align: 1px;
	}
	.cp-chip-why {
		cursor: help;
	}
	.cp-assumed-val {
		padding: 0 4px;
		border-radius: 3px;
		border: 1px dashed color-mix(in srgb, var(--rv-amber-line) 70%, transparent);
	}
	.cp-chip-read {
		opacity: 0.8;
	}
	.cp-chip-decisive {
		color: var(--rv-amber-text);
		border-color: var(--rv-amber-line);
		font-weight: 700;
	}
	/* an open question is always answerable, and a doubtful value always changeable: their buttons never hide */
	.cp-val[data-state='asked'] .cp-val-change,
	.cp-val--doubt .cp-val-change {
		opacity: 1;
	}
	.cp-val--doubt {
		background: var(--rv-amber-bg);
		box-shadow: inset 3px 0 0 var(--rv-amber-line);
	}
	.cp-val-change {
		margin-left: 2px;
		font-size: 0.75rem;
		color: var(--rv-muted);
		opacity: 0;
		text-decoration: none;
	}
	/* quiet until the row is hovered or focused; always there for keyboard and touch */
	.cp-val:hover .cp-val-change,
	.cp-val:focus-within .cp-val-change,
	.cp-val-change:focus-visible {
		opacity: 1;
	}
	@media (hover: none) {
		.cp-val-change {
			opacity: 1;
		}
	}
	/* a bubble under the row, out of the flow: revealing it never moves what is below (or under the pointer) */
	.cp-quote {
		display: none;
		position: absolute;
		left: 0;
		right: 0;
		top: 100%;
		z-index: 5;
		margin-top: 2px;
		padding: 5px 8px;
		border-radius: 6px;
		border: 1px solid var(--rv-border-strong);
		background: var(--rv-overlay);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
		font-size: 0.8125rem;
		color: var(--rv-text);
		pointer-events: none;
	}
	.cp-quote-text {
		display: block;
		font-style: italic;
	}
	.cp-why {
		display: block;
		color: var(--rv-amber-text);
	}
	.cp-val:hover .cp-quote,
	.cp-val:focus .cp-quote {
		display: block;
	}
	:global(.cp-compact) .cp-val-label {
		flex-basis: 100%;
	}
</style>
