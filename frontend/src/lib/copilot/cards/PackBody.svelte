<script lang="ts">
	/**
	 * An opened pack card's body: the four-zone questionnaire (spec 2026-10-14 §4). Top to bottom:
	 * 1. (the head, in PackCard: guideline · result pill · assumptions chip);
	 * 2. the status line (what stands between the card and a recommendation);
	 * 3. Check: only the decisive guessed values (and scope doubts) the radiologist must affirm;
	 * 4. "Based on": every other value, collapsed (editable, with provenance); N/A behind "+N not applicable";
	 * 5. the answers so far, as chips, then ONE question at a time ("Not known" always offered);
	 * 6. the result, once and live: the draft outcome (headline, what the recommendation adds, classification), or the
	 *    candidates to pick from, then Apply when the Apply flag is on;
	 * 7. notes and source, collapsed.
	 * A card that does not apply leads with the specific reason; its values wait behind "values". `compact` (a
	 * side-by-side sibling column) shows the status line only when it can be acted on, keeps Based on collapsed, and
	 * has no question or Apply unless the column is answerable (the parent binds the handlers).
	 */
	import type { AppliedRec } from '$lib/hybrid-stack/types';
	import { verdictKey } from '../gate';
	import { NOT_STATED } from '../state';
	import type { OpenResult } from '../types';
	import AnswerChips from './AnswerChips.svelte';
	import CheckZone from './CheckZone.svelte';
	import NextQuestion from './NextQuestion.svelte';
	import ValueEdit from './ValueEdit.svelte';
	import ResultZone from './ResultZone.svelte';
	import { answeredChips, basedOn, checkItems, collapsedReason, collapsible, nextAsk, readiness, remaining } from './questionnaire';
	import CollapsedRow from './CollapsedRow.svelte';
	import type { Unresolved } from '../gate';
	import Icon, { type IconName } from './Icon.svelte';
	import {
		allValueRows,
		assumptionsOf,
		categoryColor,
		categoryText,
		decidingQuestion,
		notNeededRows,
		openQuestions,
		scopeDoubts,
		restates,
		displayValue,
		shownValue,
		sourcesOf,
		verdictOf,
		type Verdict
	} from './format';
	import Reference from './Reference.svelte';
	import ValueRow from './ValueRow.svelte';

	let {
		result,
		compact = false,
		assumptions = null,
		verdict = undefined,
		onEdit = null,
		busy = false,
		editError = null,
		guideline = '',
		edits = {},
		ticks = {},
		pick = null,
		applying = false,
		applyError = null,
		applied = null,
		applyOn = false,
		onTick = null,
		onPick = null,
		onApply = null,
		expanded = undefined,
		onExpand = null,
		unresolved = null,
		onSeen = null
	}: {
		result: OpenResult;
		compact?: boolean;
		/** The assumed eligibility checks; null derives them (assumptionsOf). */
		assumptions?: string[] | null;
		/** The verdict the head shows; derived from the preview when not given. */
		verdict?: Verdict | null;
		/** Answer or change a value (the card re-previews and the result follows). Absent: read-only. */
		onEdit?: ((input: string, value: string) => void) | null;
		/** The card is re-previewing after an edit: the result shown is about to update. */
		busy?: boolean;
		editError?: string | null;
		/** The guideline's name, for the applicability warning. */
		guideline?: string;
		/** The card's answers (input → value; "Not stated" = Not known) and ticks (input → the value affirmed). */
		edits?: Record<string, string>;
		ticks?: Record<string, string>;
		pick?: string | null;
		applying?: boolean;
		applyError?: string | null;
		applied?: AppliedRec | null;
		applyOn?: boolean;
		onTick?: ((input: string, value: string) => void) | null;
		onPick?: ((outcome: string | null) => void) | null;
		onApply?: (() => void) | null;
		/** A card that may not apply is collapsed to one row; the view owns whether it is open (the gate opens it). */
		expanded?: boolean;
		onExpand?: ((open: boolean) => void) | null;
		/** The gate blocks Confirm on this guideline: its one note sits above the result. */
		unresolved?: Unresolved | null;
		onSeen?: ((key: string) => void) | null;
	} = $props();

	const p = $derived(result.preview);
	const v = $derived(verdict === undefined ? verdictOf(p) : verdict);
	const rows = $derived(allValueRows(result));
	const assumed = $derived(assumptions ?? assumptionsOf(p));
	// a pre-Task 3 preview has no draft: its open questions are not in the value list
	const questions = $derived(p && !p.draft?.length ? openQuestions(p) : []);
	const src = $derived(sourcesOf(v?.citations ?? []));
	const decided = $derived(!!v && v.category !== 'open' && !v.tentative);
	const longText = $derived(!!v && v.classification.length > 110);
	// an exclusion worded by its outcome (§7.12 item 1) says what to do instead; a generic one has no action
	// the opened card's pill is only the category word, so the verdict carries the whole recommendation
	const recText = $derived(v ? (v.excluded ? v.action : v.recommendation || v.action) : '');
	// asked inputs that cannot change the outcome wait behind "N not needed on this branch" (§7.12 item 3)
	// (a card that does not apply keeps them in its values list: nothing there can change the outcome)
	const notNeededIds = $derived(new Set(v?.excluded ? [] : notNeededRows(p).map((r) => r.input)));
	const notNeededList = $derived(rows.filter((r) => notNeededIds.has(r.input)));
	let showNotNeeded = $state(false);
	const shownRows = $derived(rows.filter((r) => r.state !== 'not_applicable' && !notNeededIds.has(r.input)));
	const naRows = $derived(rows.filter((r) => r.state === 'not_applicable'));
	let showNa = $state(false);
	let showValues = $state(false);
	let showMore = $state(false);
	let showNotes = $state(false);
	let showSource = $state(false);
	let showPossible = $state(false);
	let openNote = $state<number | null>(null);
	const uid = $props.id(); // ids for aria-controls / aria-describedby
	const icon: Record<string, IconName> = { none: 'check', surveillance: 'clock', workup: 'search', refer: 'alert', info: 'info', not_applicable: 'info', neutral: 'dot', open: 'open' };
	const likely = $derived(p?.most_likely ?? null);
	const branches = $derived((p?.deciding ?? []).slice(0, 3));
	const decidingQ = $derived(p ? decidingQuestion(p) : '');
	const underAssumptions = $derived(assumed.length > 0 || !!p?.assumed_eligible);
	// pre-filled values that would make the guideline not apply: never silent (Hassan's rule), shown first
	const doubts = $derived(scopeDoubts(p));
	const doubtIds = $derived(new Set(doubts.map((d) => d.input)));
	const check = $derived(checkItems(p, ticks));
	const next = $derived(nextAsk(p, edits));
	const chips = $derived(answeredChips(p, edits));
	const pickNow = $derived(p?.draft_outcome ? null : pick); // a leftover pick never counts once an outcome is reached
	const blocker = $derived(readiness(p, edits, ticks, pickNow));
	const cands = $derived(p && !p.draft_outcome && !next && p.state !== 'does_not_apply' ? (p.candidates ?? []) : []);
	// the toggle names where the other values came from, on two lines: read from the dictation (or set by the exam),
	// then the guesses that do not decide the outcome (and the answers the radiologist gave)
	const basedLines = $derived.by(() => {
		const list = basedOn(p, check);
		const part = (head: string, rs: typeof list) => (rs.length ? `${head}: ${rs.map((d) => `${d.label} ${displayValue(d.value, d.basis ?? '')}`).join(' · ')}` : '');
		const guess = (d: (typeof list)[number]) => (d.state === 'prefilled' || d.state === 'assumed') && d.by !== 'exam';
		const line1 = [part('Read from your dictation', list.filter((d) => d.state === 'read' && d.by !== 'exam')), part('Set by the exam', list.filter((d) => d.by === 'exam'))].filter(Boolean).join('; ');
		const line2 = part('Also used (not decisive)', list.filter(guess));
		// the radiologist's own answers are the strongest provenance: their own line, first
		const mine = part('Answered by you', list.filter((d) => d.state === 'answered' || d.state === 'edited'));
		return [mine, line1, line2].filter(Boolean);
	});
	let editingChip = $state<string | null>(null);
	let doubtEditing = $state<string | null>(null); // the excluded layout's scope-doubt banner only
	let localOpen = $state(false); // without a view (onExpand), the body keeps its own open state
	const canCollapse = $derived(collapsible(p));
	const isOpen = $derived(onExpand ? !!expanded : !!expanded || localOpen);
	const collapsed = $derived(canCollapse && !isOpen);
	const toggle = () => (onExpand ? onExpand(!isOpen) : (localOpen = !localOpen));
	const reason = $derived(p && canCollapse ? collapsedReason(p, v?.headline ?? '') : null);
	const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
	// the recommendation slot: an outcome, a scope doubt's "if it applies", or the likeliest outcome and what decides it
	const likelyBlock = $derived(!decided && !next && !v?.ifApplies && (!!likely || (branches.length > 0 && !!decidingQ)));
	const slotHasRec = $derived(decided || !!v?.ifApplies || likelyBlock);
	// provisional while the card is not ready (values can be ticked: Apply on) or rests on values not dictated
	// (otherwise), or no outcome yet: the amber dashed border cue and one ◐ line, never a fade
	const unconfirmed = $derived(check.filter((c) => !c.affirmed).length);
	const canTick = $derived(applyOn && !!onTick);
	const provisionalCue = $derived(blocker === 'question' || (canTick ? blocker !== null : check.length > 0));
	const provisional = $derived.by(() => {
		if (blocker === 'question') return 'Provisional — answer the question above to settle it';
		if (!provisionalCue) return '';
		if (!canTick) return `Rests on ${plural(check.length, 'value', 'values')} not stated in your dictation — check them below`;
		if (blocker === 'check') return `Provisional — confirm the ${plural(unconfirmed, 'value', 'values')} below to use it`;
		if (blocker === 'pick') return 'Provisional — choose the outcome that fits below';
		return 'Provisional — answer the open question below to use it';
	});
	// the question slot holds only the questions the card asked (now or answered: an "answered" row, or still in asks)
	const askChips = $derived(chips.filter((c) => p?.draft?.find((d) => d.input === c.input)?.state === 'answered' || !!p?.asks.some((a) => a.input === c.input)));
	const missing = $derived(askChips.find((c) => c.value === NOT_STATED) ?? null);
	let slotH = $state(0);
	let heldH = $state(0); // the slot keeps the height of the question it showed, so the recommendation never jumps
	$effect(() => {
		if (next && slotH) heldH = slotH;
		else if (!next && askChips.length === 0) heldH = 0; // nothing asked or answered: no gap left behind
	});
	const questionLabel = $derived(`QUESTION ${askChips.length + 1} OF ${p?.bounded === false ? 'UP TO ' : ''}${askChips.length + remaining(p, edits)}`);
</script>

{#snippet verdictBlock(vv: Verdict, cue: boolean)}
	<section
		class="cp-verdict"
		class:cp-rec-provisional={cue}
		style:--cp-cat={categoryColor(vv.category)}
		style:--cp-cat-text={categoryText(vv.category)}
		data-cat={vv.category}
		data-testid={vv.excluded ? 'cp-exclusion' : undefined}
		aria-label="Verdict"
		aria-busy={busy}
	>
		<p class="cp-p cp-headline">{vv.headline}</p>
		<!-- the pill is only the category word: the whole recommendation (the action and its later steps) shows here -->
		{#if recText}<p class="cp-p cp-recommendation">{recText}</p>{/if}
		{#if vv.excluded && vv.classification && vv.classification !== vv.headline}
			<!-- does not apply: the specific reason leads; the generic exclusion text waits behind "full reason" -->
			<button type="button" class="rv-btn rv-btn-ghost cp-more" aria-expanded={showMore} aria-controls="{uid}-cls" onclick={() => (showMore = !showMore)}
				>{showMore ? 'hide full reason' : 'full reason'}</button
			>
			<p class="cp-p cp-classification" id="{uid}-cls" hidden={!showMore}>{vv.classification}</p>
		{:else if vv.classification && vv.classification !== vv.headline && !restates(vv.classification, vv.headline)}
			<p class="cp-p cp-classification" class:cp-clamp={longText && !showMore && !compact} id="{uid}-cls">{vv.classification}</p>
			{#if longText && !compact}
				<button type="button" class="rv-btn rv-btn-ghost cp-more" aria-expanded={showMore} aria-controls="{uid}-cls" onclick={() => (showMore = !showMore)}
					>{showMore ? 'less' : 'more'}</button
				>
			{/if}
		{/if}
		<p class="cp-p cp-onvalues" aria-live="polite">{#if busy}Updating on the new values…{/if}</p>
	</section>
{/snippet}

{#snippet valuesBlock()}
	{#if rows.length}
		<section class="cp-values" aria-label="Values">
			{#if v?.excluded}
				<!-- a card that does not apply keeps its values out of the way -->
				<button type="button" class="rv-btn rv-btn-ghost cp-aux-toggle" aria-expanded={showValues} aria-controls="{uid}-values" onclick={() => (showValues = !showValues)}
					>values <span class="cp-caret"><Icon name="chev" size={11} /></span></button
				>
			{:else}
				<button type="button" class="rv-btn rv-btn-ghost cp-aux-toggle cp-based" aria-expanded={showValues} aria-controls="{uid}-values" onclick={() => (showValues = !showValues)}
					>{#each basedLines as l, i (l)}<span class="cp-based-line">{l}{#if i === basedLines.length - 1} <span class="cp-caret"><Icon name="chev" size={11} /></span>{/if}</span>{/each}{#if !basedLines.length}<span class="cp-based-line">Values used <span class="cp-caret"><Icon name="chev" size={11} /></span></span>{/if}</button
				>
			{/if}
			<ul class="cp-val-list" id="{uid}-values" hidden={!showValues}>
				{#each shownRows as r (r.input)}
					<ValueRow row={r} {uid} {onEdit} doubt={doubtIds.has(r.input)} />
				{/each}
				{#if naRows.length}
					{#if showNa}
						{#each naRows as r (r.input)}<ValueRow row={r} {uid} {onEdit} />{/each}
					{/if}
					<li class="cp-na-toggle">
						<button type="button" class="rv-btn rv-btn-ghost" aria-expanded={showNa} onclick={() => (showNa = !showNa)}
							>{showNa ? 'hide not applicable' : `+${naRows.length} not applicable`}</button
						>
					</li>
				{/if}
			</ul>
		</section>
	{/if}
	{#if notNeededList.length && !v?.excluded && showValues}
		<section class="cp-not-needed" aria-label="Not needed on this branch">
			<button type="button" class="rv-btn rv-btn-ghost cp-aux-toggle" aria-expanded={showNotNeeded} aria-controls="{uid}-not-needed" onclick={() => (showNotNeeded = !showNotNeeded)}
				>{notNeededList.length} not needed on this branch <span class="cp-caret"><Icon name="chev" size={11} /></span></button
			>
			<ul class="cp-val-list" id="{uid}-not-needed" hidden={!showNotNeeded}>
				{#each notNeededList as r (r.input)}<ValueRow row={r} {uid} {onEdit} />{/each}
			</ul>
		</section>
	{/if}
{/snippet}

{#snippet footer()}
	{#if (decided && v && !compact && (v.caveats.length || src.short)) || (!compact && result.reference && !collapsed)}
	<div class="cp-aux">
		{#if decided && v && !compact}
			{#if v.caveats.length}
				<div class="cp-notes" class:cp-aux-open={showNotes}>
					<button type="button" class="rv-btn rv-btn-ghost cp-aux-toggle" aria-expanded={showNotes} aria-controls="{uid}-notes" onclick={() => (showNotes = !showNotes)}
						>{v.caveats.length} {v.caveats.length === 1 ? 'note' : 'notes'} <span class="cp-caret"><Icon name="chev" size={11} /></span></button
					>
					<ul class="cp-note-list" id="{uid}-notes" hidden={!showNotes}>
						{#each v.caveats as c, i (i)}
							<li>
								<button type="button" class="cp-note" class:cp-note--open={openNote === i} aria-expanded={openNote === i} onclick={() => (openNote = openNote === i ? null : i)}
									>{c}</button
								>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
			{#if src.short}
				<div class="cp-source" class:cp-aux-open={showSource}>
					<button type="button" class="rv-btn rv-btn-ghost cp-aux-toggle" aria-expanded={showSource} aria-controls="{uid}-src" onclick={() => (showSource = !showSource)}
						>{src.short}{#if src.more}<span class="cp-muted cp-src-more">+{src.more}</span>{/if}
						<span class="cp-caret"><Icon name="chev" size={11} /></span></button
					>
					<ul class="cp-src-list" id="{uid}-src" hidden={!showSource}>
						{#each src.full as s, i (i)}<li>{s}</li>{/each}
					</ul>
				</div>
			{/if}
		{/if}
		{#if !compact && result.reference && !collapsed}
			<Reference reference={result.reference} />
		{/if}
	</div>
	{/if}
	{#if p?.degraded}
		<p class="cp-p cp-muted cp-degraded">Some values could not be checked</p>
	{/if}
{/snippet}

<div class="cp-pack-body" class:cp-compact={compact}>
	{#if !p}
		{#if result.entry?.content.summary}<p class="cp-p">{result.entry.content.summary}</p>{/if}
		{#if !compact && result.reference}<Reference reference={result.reference} />{/if}
	{:else}
		{#if editError}<p class="cp-p cp-edit-error" role="alert">{editError}</p>{/if}
		{#if collapsed && reason}
			<CollapsedRow {reason} {guideline} onConfirm={onEdit} onToggle={toggle} controls="{uid}-body" />
		{:else}
		{#if canCollapse}<button type="button" class="rv-btn rv-btn-ghost cp-hide-details" aria-expanded="true" aria-controls="{uid}-body" onclick={toggle}>Hide details <span class="cp-caret"><Icon name="chev" size={11} /></span></button>{/if}
		<div id="{uid}-body" class="cp-body-inner">
		{#if p.state === 'does_not_apply'}
			{#each doubts as d (d.input)}
				<div class="cp-doubt" role="note" data-testid="cp-scope-doubt">
					<p class="cp-p">
						<Icon name="warn" size={13} />
						<span><b>{d.label}: {shownValue(d.value)}</b> (probably from your dictation) would make {guideline || 'this guideline'} not apply — confirm or change it</span>
					</p>
					{#if onEdit}
						<div class="cp-doubt-actions">
							{#if doubtEditing === d.input}
								<ValueEdit
									label={d.label}
									value={d.value}
									options={d.options}
									onSave={(val) => {
										doubtEditing = null;
										onEdit?.(d.input, val);
									}}
									onCancel={() => (doubtEditing = null)}
								/>
							{:else}
								<!-- confirming sends the value back as the radiologist's answer: only then can it exclude -->
								{#if d.value}<button type="button" class="rv-btn" aria-label={`Confirm ${d.label} ${shownValue(d.value)}`} onclick={() => onEdit?.(d.input, d.value)}>Confirm</button>{/if}
								<button type="button" class="rv-btn" aria-label={`Change ${d.label}`} onclick={() => (doubtEditing = d.input)}>Change</button>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
			<!-- a card that does not apply keeps today's order: its values behind "values", then why -->
			{@render valuesBlock()}
			{#if decided && v}{@render verdictBlock(v, false)}{/if}
			{@render footer()}
		{:else}
			<!-- 1. QUESTION: the deciding question leads; answered, its slot becomes the answered line and the recommendation below updates in place -->
			{#if onEdit && (askChips.length || next)}
				<section class="cp-sect cp-qslot" data-testid="cp-section" aria-label="Question" bind:clientHeight={slotH} style:min-height={!next && heldH ? `${heldH}px` : undefined}>
					{#if next}<div class="cp-sect-label" data-testid="cp-section-label">{questionLabel}</div>{/if}
					<AnswerChips chips={askChips} bind:editing={editingChip} onAnswer={onEdit} />
					{#if next}{#key next.input}<NextQuestion ask={next} onAnswer={onEdit} />{/key}{/if}
				</section>
			{/if}
			{#if questions.length && !onEdit}
				<section class="cp-open-q" aria-label="Still open">
					<div class="cp-label">Still open</div>
					<ul class="cp-open-list">
						{#each questions as q, i (i)}<li>{q}</li>{/each}
					</ul>
				</section>
			{/if}

			<!-- 2. RECOMMENDATION: what the card would tell the report, cued (dashed border, ◐ line) while it is provisional -->
			{#if slotHasRec || next || cands.length || p.possible.length}
				<section class="cp-sect" data-testid="cp-section" aria-label="Recommendation">
					<div class="cp-sect-label" data-testid="cp-section-label">RECOMMENDATION</div>
					{#if decided && v}
						{@render verdictBlock(v, provisionalCue)}
					{:else if v?.ifApplies}
						<p class="cp-p cp-if-applies" class:cp-rec-provisional={provisionalCue} data-testid="cp-if-applies">{v.ifApplies}</p>
					{:else if likelyBlock}
						<!-- no outcome yet: the likeliest one when there is one, and what genuinely decides it (max three branches);
						     the full list stays behind "show all" -->
						<section class="cp-likely" class:cp-rec-provisional={provisionalCue} aria-label={likely ? 'Most likely' : 'What decides it'}>
							{#if likely}
							<p class="cp-p cp-likely-line" style:--cp-cat={categoryColor(likely.category || 'neutral')} style:--cp-cat-text={categoryText(likely.category || 'neutral')}>
								<Icon name={icon[likely.category || 'neutral']} size={13} />
								<span>Most likely: <b>{likely.headline}</b></span>
								{#if underAssumptions}<span class="cp-chip cp-chip-warn">⚠ under assumptions</span>{/if}
							</p>
							{/if}
							{#if branches.length && decidingQ}
								<div class="cp-depends">
									<p class="cp-p">Depends on {decidingQ}</p>
									<ul class="cp-branches">
										{#each branches as b, i (i)}
											<li style:--cp-cat-text={categoryText(b.category || 'neutral')}>
												<span class="cp-branch-answer">{b.answer}</span><span class="cp-muted" aria-hidden="true">→</span><span class="cp-sr-only">:</span>
												<b>{b.headline}</b>
											</li>
										{/each}
									</ul>
								</div>
							{/if}
							{#if p.possible.length > 1}
								<button type="button" class="rv-btn rv-btn-ghost cp-possible-toggle" aria-expanded={showPossible} aria-controls="{uid}-possible" onclick={() => (showPossible = !showPossible)}
									>{showPossible ? 'hide all' : `show all ${p.possible.length}`}</button
								>
								<ul class="cp-list cp-possible-list" id="{uid}-possible" hidden={!showPossible}>
									{#each p.possible as o, i (i)}<li>{o}</li>{/each}
								</ul>
							{/if}
						</section>
					{:else if !cands.length && p.possible.length === 1}
						<p class="cp-p">{p.possible[0]}</p>
					{:else if !cands.length && p.possible.length > 1}
						<section class="cp-possible">
							<button type="button" class="rv-btn rv-btn-ghost cp-possible-toggle" aria-expanded={showPossible} aria-controls="{uid}-possible" onclick={() => (showPossible = !showPossible)}
								>{p.possible.length} outcomes still possible — {showPossible ? 'hide' : 'show'}</button
							>
							<ul class="cp-list cp-possible-list" id="{uid}-possible" hidden={!showPossible}>
								{#each p.possible as o, i (i)}<li>{o}</li>{/each}
							</ul>
						</section>
					{:else if next}
						<p class="cp-p cp-no-rec cp-rec-provisional">No recommendation yet — {plural(remaining(p, edits), 'question', 'questions')} to answer</p>
					{:else if cands.length}
						<p class="cp-p cp-no-rec">{applyOn && onPick ? 'Choose the outcome that fits below' : `${cands.length} outcomes are still possible — see below`}</p>
					{/if}
					{#if provisional && !(cands.length && !slotHasRec && !next && blocker === 'pick')}<p class="cp-p cp-provisional" data-testid="cp-provisional">◐ {provisional}</p>{/if}
				</section>
			{/if}

			<!-- 3. WHAT THIS RESTS ON: the values the radiologist did not dictate, then every other value used -->
			{#if check.length}
				<section class="cp-sect" data-testid="cp-section" aria-label="What this rests on">
					<div class="cp-sect-label" data-testid="cp-section-label">WHAT THIS RESTS ON</div>
					<p class="cp-p cp-muted cp-rests-note" data-testid="cp-rests-note">
						Not verified in your dictation. {applyOn && onTick ? 'Confirm each one, or change it.' : 'Change any that are wrong.'}
					</p>
					<CheckZone items={check} {guideline} onTick={applyOn ? onTick : null} {onEdit} />
					{@render valuesBlock()}
				</section>
			{:else}
				{@render valuesBlock()}
			{/if}

			<!-- 4. YOUR REPORT: the outcome pick, the gate note, Apply to report and Not in this report -->
			<ResultZone candidates={cands} pick={pickNow} {blocker} missingLabel={missing?.label ?? ''} {applyOn} {applied} current={verdictKey(p)} currentOutcome={pickNow ?? ((p.trace?.['outcome'] as string | undefined) ?? null)} {applying} {applyError} {unresolved}
				onPick={applyOn ? onPick : null} {onApply} {onSeen} onAnswerMissing={missing && onEdit ? () => (editingChip = missing.input) : null} />

			<!-- 5. notes and sources: a quiet footer -->
			{@render footer()}
		{/if}
		</div>
		{/if}
	{/if}
</div>

<style>
	.cp-pack-body {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}
	.cp-pack-body section {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.cp-p {
		margin: 0;
	}

	/* ── 1. the verdict: the one loud thing on the card ── */
	.cp-verdict {
		gap: 4px;
	}
	.cp-headline {
		font-size: 1.0625rem;
		font-weight: 650;
		line-height: 1.3;
		letter-spacing: -0.01em;
		color: var(--rv-text);
	}
	/* a collapsed list stays collapsed wherever the body renders (cards.css covers it only inside the rail list) */
	.cp-val-list[hidden] {
		display: none;
	}
	.cp-not-needed {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.75rem;
	}
	.cp-if-applies {
		font-size: 0.8125rem;
		line-height: 1.45;
		color: var(--rv-muted);
	}
	.cp-na-toggle {
		list-style: none;
		margin-top: 2px;
		font-size: 0.75rem;
	}
	.cp-recommendation {
		font-size: 0.875rem;
		line-height: 1.45;
		color: var(--rv-text);
	}
	.cp-classification {
		margin-top: 2px;
		font-size: 0.8125rem;
		line-height: 1.45;
		color: var(--rv-muted);
	}
	.cp-clamp {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.cp-more {
		align-self: flex-start;
		font-size: 0.75rem;
	}
	/* the busy note is for screen readers: the live region stays in the tree, off screen */
	.cp-onvalues {
		position: absolute;
		width: 1px;
		height: 1px;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
	}
	.cp-body-inner {
		display: contents;
	}
	/* ── 2–3. notes and source: two quiet lines ── */
	/* notes, sources and Reference: one wrapping row of small buttons; an open one takes the full row */
	.cp-aux {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 6px;
		font-size: 0.8125rem;
	}
	.cp-aux > :global(*) {
		min-width: 0;
	}
	.cp-aux-open {
		flex: 1 1 100%;
	}
	.cp-based-line {
		display: block;
	}
	.cp-aux-toggle {
		align-self: flex-start;
		text-align: left;
		color: var(--rv-muted);
		text-decoration: none;
	}
	.cp-caret {
		display: inline-block;
		margin-left: 2px;
		transition: transform 0.15s;
	}
	.cp-aux-toggle[aria-expanded='true'] .cp-caret {
		transform: rotate(90deg);
	}
	.cp-src-more {
		margin-left: 6px;
	}
	@media (prefers-reduced-motion: reduce) {
		.cp-caret {
			transition: none;
		}
	}
	.cp-aux-toggle:hover {
		color: var(--rv-text);
	}
	.cp-aux-toggle[aria-expanded='true'] {
		color: var(--rv-text);
	}
	.cp-note-list,
	.cp-src-list {
		max-height: 16rem;
		overflow-y: auto;
		overscroll-behavior: contain;
		margin: 4px 0 2px;
		padding-left: 14px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.cp-src-list {
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.cp-note {
		display: -webkit-box;
		-webkit-line-clamp: 1;
		line-clamp: 1;
		-webkit-box-orient: vertical;
		overflow: hidden;
		width: 100%;
		padding: 0;
		font: inherit;
		font-size: 0.8125rem;
		line-height: 1.45;
		text-align: left;
		color: var(--rv-text);
		background: none;
		border: 0;
		cursor: pointer;
	}
	.cp-note--open {
		display: block;
		-webkit-line-clamp: unset;
		line-clamp: unset;
	}

	/* ── 4. values: lighter than the verdict ── */
	.cp-values {
		padding-top: 10px;
		border-top: 1px solid var(--rv-border);
		font-size: 0.8125rem;
	}
	.cp-val-list {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.cp-open-q {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-open-list {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.cp-open-list li {
		padding: 1px 7px;
		border-radius: 5px;
		border: 1px dashed var(--rv-border-strong);
	}
	.cp-likely-line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 6px;
		font-size: 0.875rem;
		color: var(--cp-cat-text);
	}
	.cp-likely-line :global(.cp-icon) {
		color: var(--cp-cat);
	}
	.cp-likely-line b {
		font-weight: 650;
	}
	.cp-depends {
		font-size: 0.8125rem;
		color: var(--rv-muted);
		line-height: 1.5;
	}
	.cp-branches {
		margin: 2px 0 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.cp-branches li {
		display: flex;
		gap: 6px;
		align-items: baseline;
	}
	.cp-branch-answer {
		min-width: 6.5em;
	}
	.cp-branches b {
		font-weight: 600;
		color: var(--cp-cat-text);
	}
	.cp-values:first-child {
		padding-top: 0;
		border-top: 0;
	}
	/* the result follows the values under a rule */
	/* provisional: fully legible, marked by a dashed left border (and the ◐ line beneath) */
	.cp-rec-provisional {
		border-left: 2px dashed var(--rv-amber-line);
		padding-left: 8px;
	}
	.cp-provisional {
		font-size: 0.8125rem;
		color: var(--rv-amber-text);
	}
	.cp-rests-note {
		font-size: 0.8125rem;
	}
	.cp-doubt {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 10px;
		border-radius: 8px;
		border: 1px solid color-mix(in srgb, var(--rv-amber-line) 55%, transparent);
		background: var(--rv-amber-bg);
		color: var(--rv-text);
		font-size: 0.8125rem;
	}
	.cp-doubt p {
		display: flex;
		gap: 6px;
		align-items: flex-start;
	}
	.cp-doubt p :global(.cp-icon) {
		color: var(--rv-amber-text);
		margin-top: 2px;
	}
	.cp-doubt-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.cp-edit-error {
		font-size: 0.8125rem;
		color: var(--rv-red-text);
	}
	.cp-possible-toggle {
		align-self: flex-start;
		text-align: left;
	}
	.cp-possible-toggle {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-possible-list {
		margin-top: 4px;
		font-size: 0.8125rem;
	}
	.cp-compact {
		font-size: 0.8125rem;
	}
	.cp-compact .cp-headline {
		font-size: 0.9375rem;
	}
	.cp-degraded {
		font-size: 0.8125rem;
		font-style: italic;
	}
</style>
