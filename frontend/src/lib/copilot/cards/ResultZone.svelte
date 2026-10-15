<script lang="ts">
	/**
	 * The result's end (spec 2026-10-14 §4.4, §7): the outcomes to pick from (only while none is reached and no
	 * question is left), then Apply when the Apply flag is on: enabled once the card is ready; "Answer [question] to
	 * apply" for a pick whose sentence needs a "Not known" answer; "Applied · in Recommendations" once its current
	 * outcome is applied.
	 */
	import type { AppliedRec } from '$lib/hybrid-stack/types';
	import type { Candidate } from '../types';
	import type { Blocker } from './questionnaire';

	let {
		candidates = [],
		pick = null,
		blocker,
		missingLabel = '',
		applyOn = false,
		applied = null,
		current = '',
		applying = false,
		applyError = null,
		onPick = null,
		onApply = null,
		onAnswerMissing = null
	}: {
		candidates?: Candidate[];
		pick?: string | null;
		blocker: Blocker;
		missingLabel?: string;
		applyOn?: boolean;
		applied?: AppliedRec | null;
		current?: string;
		applying?: boolean;
		applyError?: string | null;
		onPick?: ((outcome: string | null) => void) | null;
		onApply?: (() => void) | null;
		onAnswerMissing?: (() => void) | null;
	} = $props();
	const uid = $props.id();
	const isApplied = $derived(!!applied && !applied.stale && applied.verdict === current);
	const showApply = $derived(applyOn && !!onApply && (blocker === null || blocker === 'check' || blocker === 'incomplete'));
</script>

{#if candidates.length}
	<fieldset class="cp-pick" data-testid="cp-pick">
		<legend class="cp-label">{candidates.length} outcomes still possible{onPick ? ' — pick the one that fits' : ''}</legend>
		{#if onPick}
			{#each candidates as c (c.outcome)}
				<label class="cp-pick-row"><input type="radio" name="{uid}-pick" value={c.outcome} checked={pick === c.outcome} onchange={() => onPick?.(c.outcome)} /><span>{c.headline}</span></label>
			{/each}
		{:else}
			<ul class="cp-list">
				{#each candidates as c (c.outcome)}<li>{c.headline}</li>{/each}
			</ul>
		{/if}
	</fieldset>
{/if}
{#if showApply}
	<div class="cp-apply" data-testid="cp-apply">
		{#if blocker === 'incomplete'}
			<button type="button" class="rv-btn" disabled={!onAnswerMissing} onclick={() => onAnswerMissing?.()}>Answer {missingLabel || 'the open question'} to apply</button>
		{:else if isApplied}
			<p class="cp-p cp-applied">Applied · in Recommendations</p>
		{:else}
			<button type="button" class="rv-btn rv-btn-primary" disabled={blocker !== null || applying} title={blocker === 'check' ? 'Confirm the values above first' : undefined} onclick={() => onApply?.()}>{applying ? 'Applying…' : 'Apply'}</button>
		{/if}
		{#if applyError}<p class="cp-p cp-apply-error" role="alert">{applyError}</p>{/if}
	</div>
{/if}

<style>
	.cp-pick { margin: 0; padding: 0; border: 0; display: flex; flex-direction: column; gap: 4px; font-size: 0.8125rem; }
	.cp-pick-row { display: flex; gap: 6px; align-items: center; }
	.cp-apply { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
	.cp-applied { font-size: 0.8125rem; color: var(--rv-muted); }
	.cp-apply-error { font-size: 0.8125rem; color: var(--rv-red-text); }
</style>
