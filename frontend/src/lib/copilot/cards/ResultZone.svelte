<script lang="ts">
	/**
	 * "Your report" (spec 2026-10-14 §4.4, §7): the outcomes to pick from (only while none is reached and no question
	 * is left), the gate note ("Not in your conclusion yet.") and the actions on one row: Apply to report when the Apply
	 * flag is on (enabled once the card is ready; "Answer [question] to apply" for a pick whose sentence needs a "Not
	 * known" answer; "Applied · in Recommendations" once its current outcome is applied) and Not in this report. Omitted when
	 * there is nothing to say.
	 */
	import type { AppliedRec } from '$lib/hybrid-stack/types';
	import type { Unresolved } from '../gate';
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
		currentOutcome = null,
		applying = false,
		applyError = null,
		unresolved = null,
		onPick = null,
		onApply = null,
		onSeen = null,
		onAnswerMissing = null
	}: {
		candidates?: Candidate[];
		pick?: string | null;
		blocker: Blocker;
		missingLabel?: string;
		applyOn?: boolean;
		applied?: AppliedRec | null;
		current?: string;
		/** The outcome on screen (the pick, or the reached outcome); Applied only when it is the one applied. */
		currentOutcome?: string | null;
		applying?: boolean;
		applyError?: string | null;
		/** The gate blocks Confirm on this guideline: its note and "Not in this report" sit here. */
		unresolved?: Unresolved | null;
		onPick?: ((outcome: string | null) => void) | null;
		onApply?: (() => void) | null;
		onSeen?: ((key: string) => void) | null;
		onAnswerMissing?: (() => void) | null;
	} = $props();
	const uid = $props.id();
	const isApplied = $derived(!!applied && !applied.stale && applied.verdict === current && applied.outcome === currentOutcome);
	const showApply = $derived(applyOn && !!onApply && (blocker === null || blocker === 'check' || blocker === 'incomplete'));
	const show = $derived(candidates.length > 0 || showApply || !!unresolved);
</script>

{#if show}
	<section class="cp-sect" data-testid="cp-section" aria-label="Your report">
		<div class="cp-sect-label" data-testid="cp-section-label">YOUR REPORT</div>
		{#if candidates.length}
			<fieldset class="cp-pick" data-testid="cp-pick">
				<legend class="cp-pick-legend">{onPick ? `Choose the outcome that fits · ${candidates.length} outcomes still possible` : `${candidates.length} outcomes still possible`}</legend>
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
		{#if unresolved}
			<p class="cp-p cp-gate-note" role="note" data-testid="cp-unresolved">
				Not in your conclusion yet.{#if !applyOn}{' '}Add it to your conclusion, or choose Not in this report.{/if}{#if unresolved.reason}<span class="cp-muted">{' '}{unresolved.reason}</span>{/if}
			</p>
		{/if}
		{#if showApply || (unresolved && onSeen)}
			<div class="cp-actions" data-testid="cp-apply">
				{#if showApply}
					{#if blocker === 'incomplete'}
						<button type="button" class="rv-btn" disabled={!onAnswerMissing} onclick={() => onAnswerMissing?.()}>Answer {missingLabel || 'the open question'} to apply</button>
					{:else if isApplied}
						<p class="cp-p cp-applied">Applied · in Recommendations</p>
					{:else}
						<button type="button" class="rv-btn rv-btn-primary" disabled={blocker !== null || applying} title={blocker === 'check' ? 'Confirm the values above first' : undefined} onclick={() => onApply?.()}>{applying ? 'Applying…' : 'Apply to report'}</button>
					{/if}
				{/if}
				{#if unresolved && onSeen}<button type="button" class="rv-btn" onclick={(e) => (e.stopPropagation(), onSeen?.(unresolved.key))}>Not in this report</button>{/if}
			</div>
		{/if}
		{#if applyError}<p class="cp-p cp-apply-error" role="alert">{applyError}</p>{/if}
	</section>
{/if}

<style>
	.cp-pick { margin: 0; padding: 0; border: 0; display: flex; flex-direction: column; gap: 4px; font-size: 0.8125rem; }
	.cp-pick-legend { padding: 0; font-size: 0.8125rem; font-weight: 600; color: var(--rv-text); }
	.cp-pick-row { display: flex; gap: 6px; align-items: center; }
	.cp-gate-note { margin: 0; font-size: 0.8125rem; color: var(--rv-text); }
	.cp-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
	.cp-applied { margin: 0; font-size: 0.8125rem; color: var(--rv-muted); }
	.cp-apply-error { margin: 0; font-size: 0.8125rem; color: var(--rv-red-text); }
</style>
