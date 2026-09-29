<script lang="ts">
	import { onDestroy } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { labConfig } from '$lib/dictation-lab/labConfig';
	import { buildCoverageFixtureLine, coverageAgreement } from '$lib/dictation-lab/coverage';
	import {
		FAST_ROUTES,
		buildSessionExport,
		summariseDecisions,
		type DecisionRecord,
		type OutcomeEvent
	} from '$lib/dictation-lab/decisionFirst';
	import type { CoverageTrace } from '$lib/dictation-lab/types';

	/** Feeds one utterance into the production scratchpad (IntelliDictateTab.injectTranscript). */
	export let inject: (text: string) => void = () => {};
	export let onClear: () => void = () => {};
	export let coverageTrace: CoverageTrace | null = null;
	export let decisions: { rec: DecisionRecord; display: string }[] = [];
	export let outcomes: OutcomeEvent[] = [];
	export let sessionStartedAt = 0;

	// ── Decision-first ─────────────────────────────────────────────────────────
	$: decisionSummary = summariseDecisions(decisions.map((d) => d.rec), outcomes);
	$: outcomeKinds = (() => {
		const m = new Map<string, Set<string>>();
		for (const o of outcomes) m.set(o.decision_id, (m.get(o.decision_id) ?? new Set()).add(o.kind));
		return m;
	})();
	const pct = (k: number, n: number): string => (n ? `${Math.round((100 * k) / n)}%` : '—');
	const ROUTE_CLASS: Record<string, string> = {
		fast_append: 'text-emerald-300',
		command: 'text-blue-300',
		polish: 'text-amber-300',
		skip: 'text-gray-400'
	};
	/** Data only (no text): the input to scripts/lab_session_summary.py. */
	function downloadSession(): void {
		const out = buildSessionExport(decisions.map((d) => d.rec), outcomes, {
			scanType: coverageState?.scanType ?? '',
			startedAt: sessionStartedAt,
			exportedAt: Date.now()
		});
		const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = `lab-session-${new Date(sessionStartedAt).toISOString().replace(/[:.]/g, '-')}.json`;
		a.click();
		URL.revokeObjectURL(a.href);
	}

	export let coverageState: { scratchpad: string; checklist: string[]; scanType: string } | null = null;

	// ── Coverage ───────────────────────────────────────────────────────────────
	let coverageBuffer = '';
	let coverageSeq = 1;
	let covExp = { expected: new Set<string>(), rule: 'direct-subject', hard: false, note: '' };
	const RULES = [
		'direct-subject', 'direct-location', 'direct-modifier', 'collective-group', 'collective-boundary',
		'specific-overrides-collective', 'bare-mention', 'adjacent-structure', 'parent-not-enumerating',
		'incidental-co-mention', 'vague-filler', 'abbreviation'
	];
	$: sections = coverageState?.checklist ?? [];
	$: agreement =
		coverageTrace?.jev?.scores && coverageTrace?.qwen?.covered
			? coverageAgreement(sections, coverageTrace.jev.scores, coverageTrace.qwen.covered)
			: ({} as Record<string, string>);
	function startCoverageExport(): void {
		const jev = coverageTrace?.jev?.scores ?? {};
		covExp = { expected: new Set(sections.filter((s) => (jev[s] ?? 0) >= 0.5)), rule: 'direct-subject', hard: false, note: '' };
	}
	function toggleExpected(s: string): void {
		const n = new Set(covExp.expected);
		if (n.has(s)) n.delete(s);
		else n.add(s);
		covExp = { ...covExp, expected: n };
	}
	function appendCoverageLine(): void {
		if (!coverageState) return;
		const line = buildCoverageFixtureLine(coverageState, {
			id: `lab-cov-${String(coverageSeq++).padStart(2, '0')}`,
			expected_covered: sections.filter((s) => covExp.expected.has(s)),
			rule: covExp.rule,
			hard: covExp.hard,
			note: covExp.note
		});
		coverageBuffer = coverageBuffer ? `${coverageBuffer}\n${line}` : line;
	}

	// ── Feeder ─────────────────────────────────────────────────────────────────
	let feederText = '';
	let cursor = 0;
	let delayMs = 1500;
	let playing = false;
	let timer: ReturnType<typeof setTimeout> | null = null;

	$: lines = feederText
		.split('\n')
		.map((l) => l.trim())
		.filter(Boolean);

	function step(): void {
		if (cursor >= lines.length) {
			stop();
			return;
		}
		inject(lines[cursor]);
		cursor += 1;
	}
	function play(): void {
		if (playing) return;
		playing = true;
		const tick = () => {
			if (!playing || cursor >= lines.length) {
				stop();
				return;
			}
			step();
			timer = setTimeout(tick, delayMs);
		};
		tick();
	}
	function stop(): void {
		playing = false;
		if (timer) {
			clearTimeout(timer);
			timer = null;
		}
	}
	function resetFeeder(): void {
		stop();
		cursor = 0;
	}
	onDestroy(stop);

</script>

<div class="space-y-4 text-sm">
	<!-- Strategy -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">Strategy</h3>
		<div class="flex flex-wrap gap-3">
			<span class="text-gray-400">front door</span>
			{#each [['timer', 'silence timers'], ['decision', 'decision-first (live)']] as [value, label]}
				<label class="flex items-center gap-1">
					<input type="radio" bind:group={$labConfig.frontDoor} {value} />
					{label}
				</label>
			{/each}
		</div>
		{#if $labConfig.frontDoor === 'decision'}
			<div class="flex flex-wrap gap-3">
				<span class="text-gray-400">polish</span>
				{#each [['full', 'full rewrite (today)'], ['race', 'lean span, raced with Jev']] as [value, label]}
					<label class="flex items-center gap-1">
						<input type="radio" bind:group={$labConfig.polish} {value} />
						{label}
					</label>
				{/each}
				<span class="text-gray-500 text-xs">(race: Verbatim mode only)</span>
			</div>
		{/if}
	</section>

	<!-- Decision-first (front door 'decision') -->
	{#if $labConfig.frontDoor === 'decision' || decisions.length > 0}
		<section class="card-dark space-y-2">
			<h3 class="font-semibold flex items-baseline gap-2">
				Decision-first
				<span class="text-gray-400 font-normal text-xs">
					{decisionSummary.utterances} utterances · {decisionSummary.polishCalls} polish calls (baseline {decisionSummary.utterances})
					· {decisionSummary.avoided} avoided ({pct(decisionSummary.avoided, decisionSummary.utterances)})
					· bundle p50 {decisionSummary.bundleP50 ?? '—'} / p95 {decisionSummary.bundleP95 ?? '—'} ms
				</span>
				<button class="btn-secondary text-xs ml-auto" on:click={downloadSession} disabled={!decisions.length}>Export session</button>
			</h3>
			<div class="grid grid-cols-5 gap-x-2 text-xs tabular-nums">
				<span class="text-gray-400">route</span><span class="text-gray-400">n</span><span class="text-gray-400">undo</span>
				<span class="text-gray-400">edit ≤10 s</span><span class="text-gray-400">re-dictated</span>
				{#each FAST_ROUTES as r}
					{@const c = decisionSummary.byRoute[r]}
					<span class={ROUTE_CLASS[r]}>{r.replace('_', '-')}</span><span>{c.n}</span>
					<span>{c.undo} ({pct(c.undo, c.n)})</span><span>{c.edit} ({pct(c.edit, c.n)})</span><span>{c.redictate} ({pct(c.redictate, c.n)})</span>
				{/each}
			</div>
			<div class="max-h-56 overflow-y-auto space-y-0.5">
				{#each decisions as d (d.rec.id)}
					{@const k = outcomeKinds.get(d.rec.id)}
					<div class="text-xs flex flex-wrap gap-x-2 items-baseline border-l-2 pl-2 border-gray-700">
						<span class="text-gray-500 tabular-nums">#{d.rec.seq}</span>
						<span class="font-mono truncate max-w-[12rem]">“{d.display}”</span>
						<span class={ROUTE_CLASS[d.rec.route]}>{d.rec.route.replace('_', '-')}</span>
						<span class="text-gray-500">{d.rec.reason}</span>
						{#if d.rec.confidence != null}<span class="tabular-nums text-gray-400">{d.rec.action?.split('_')[0]} {d.rec.confidence.toFixed(2)}</span>{/if}
						{#if d.rec.standalone != null}<span class="tabular-nums text-gray-500">sa {d.rec.standalone.toFixed(2)}</span>{/if}
						{#if d.rec.asr_min_conf != null}<span class="tabular-nums {d.rec.asr_min_conf < 0.8 ? 'text-orange-300' : 'text-gray-500'}" title="lowest Deepgram word confidence">asr {d.rec.asr_min_conf.toFixed(2)}</span>{/if}
						<span class="tabular-nums text-gray-500">{d.rec.latency_ms ?? '—'} ms</span>
						{#if d.rec.polish_ms != null}<span class="tabular-nums text-amber-200/70">{d.rec.polish_kind ?? 'polish'} {d.rec.polish_ms} ms{d.rec.polish_tokens_in != null ? ` · ${d.rec.polish_tokens_in}+${d.rec.polish_tokens_out ?? 0} tok` : ''}</span>{/if}
						{#if d.rec.asr_fix_count}<span class="text-emerald-300" title="word-sense fixes applied">fixed {d.rec.asr_fix_count}{d.rec.repair_ms != null ? ` · ${d.rec.repair_ms} ms` : ''}</span>{/if}
						{#if d.rec.asr_flag_count}<span class="text-yellow-300" title="words underlined as not making clinical sense">flagged {d.rec.asr_flag_count}</span>{/if}
						{#if d.rec.two_pass_switched}<span class="text-emerald-300" title="two-pass: words swapped (Jev ≥ 0.90)">2p swapped {d.rec.two_pass_switched}</span>{/if}
						{#if d.rec.two_pass_suggested}<span class="text-yellow-300" title="two-pass: underlined, also heard as …">2p suggested {d.rec.two_pass_suggested}</span>{/if}
						{#if d.rec.two_pass_inserted}<span class="text-sky-300" title="two-pass: dropped negation / side / number inserted">2p inserted {d.rec.two_pass_inserted}</span>{/if}
						{#if d.rec.two_pass_recovered_words}<span class="text-sky-300" title="two-pass: dropped speech recovered">2p recovered {d.rec.two_pass_recovered_words}w</span>{/if}
						{#if d.rec.two_pass_ms != null}<span class="text-gray-500" title="two-pass revision time after the final">2p {d.rec.two_pass_ms} ms</span>{/if}
						{#if d.rec.line_closed_by}<span class="text-violet-300">⏎ {d.rec.line_closed_by}</span>{/if}
						{#if k}{#each [...k] as kind}<span class="text-red-300">{kind}</span>{/each}{/if}
						{#if d.rec.error}<span class="text-red-300">{d.rec.error}</span>{/if}
					</div>
				{/each}
			</div>
		</section>
	{/if}

	<!-- Coverage -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">
			Coverage
			<span class="text-gray-400 font-normal text-xs">
				{#if coverageTrace}selected={coverageTrace.selected} · jev {coverageTrace.jev?.latency_ms ?? '—'} ms · qwen {coverageTrace.qwen?.latency_ms ?? '—'} ms{/if}
			</span>
		</h3>
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={$labConfig.coverageDebug} />
			compare both candidates (coverage_debug)
		</label>
		<div class="flex gap-4 text-xs items-center">
			<label class="flex items-center gap-1">
				hi <input type="range" min="0.5" max="1" step="0.05" bind:value={$labConfig.pillThresholds.hi} />
				<span class="tabular-nums">{$labConfig.pillThresholds.hi.toFixed(2)}</span>
			</label>
			<label class="flex items-center gap-1">
				lo <input type="range" min="0" max="0.75" step="0.05" bind:value={$labConfig.pillThresholds.lo} />
				<span class="tabular-nums">{$labConfig.pillThresholds.lo.toFixed(2)}</span>
			</label>
		</div>
		{#if coverageTrace}
			<table class="w-full text-xs">
				<thead><tr class="text-gray-400"><th class="text-left">section</th><th>jev p</th><th>qwen</th><th></th></tr></thead>
				<tbody>
					{#each sections as s}
						{@const p = coverageTrace.jev?.scores?.[s]}
						{@const q = coverageTrace.qwen?.covered?.includes(s)}
						<tr class={agreement[s] === 'agree' || !agreement[s] ? '' : agreement[s] === 'jev-only' ? 'text-amber-300' : 'text-red-300'}>
							<td>{s}</td>
							<td class="text-center tabular-nums">{p == null ? (coverageTrace.jev?.error ?? '—') : p.toFixed(2)}</td>
							<td class="text-center">{coverageTrace.qwen?.error ?? (q ? '✓' : '·')}</td>
							<td class="text-right text-gray-500">{agreement[s] ?? ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<button class="btn-secondary text-xs" on:click={startCoverageExport} disabled={!coverageState}>Add to coverage fixtures</button>
			{#if covExp.expected.size > 0 || coverageBuffer}
				<div class="flex flex-wrap gap-2">
					{#each sections as s}
						<label class="text-xs"><input type="checkbox" checked={covExp.expected.has(s)} on:change={() => toggleExpected(s)} /> {s}</label>
					{/each}
				</div>
				<div class="flex flex-wrap gap-2 items-center text-xs">
					<select class="bg-gray-900 rounded px-1" bind:value={covExp.rule}>
						{#each RULES as r}<option value={r}>{r}</option>{/each}
					</select>
					<label><input type="checkbox" bind:checked={covExp.hard} /> hard</label>
					<input class="bg-gray-900 rounded px-2 py-1 flex-1" placeholder="note" bind:value={covExp.note} />
					<button class="btn-primary text-xs" on:click={appendCoverageLine}>Append</button>
				</div>
				<textarea class="w-full h-16 bg-gray-900 rounded p-2 font-mono text-xs" readonly value={coverageBuffer}></textarea>
			{/if}
		{/if}
	</section>

	<!-- Feeder -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">
			Utterance feeder <span class="text-gray-400 font-normal">({cursor}/{lines.length})</span>
		</h3>
		<textarea
			class="w-full h-32 bg-gray-900 rounded p-2 font-mono text-xs"
			bind:value={feederText}
			placeholder="one utterance per line"
		></textarea>
		<div class="flex flex-wrap gap-2 items-center">
			<button class="btn-secondary" on:click={step} disabled={playing || cursor >= lines.length}>Step</button>
			<button class="btn-secondary" on:click={play} disabled={playing || cursor >= lines.length}>Play</button>
			<button class="btn-secondary" on:click={stop} disabled={!playing}>Stop</button>
			<label class="flex items-center gap-1">
				delay
				<input type="number" class="w-20 bg-gray-900 rounded px-1" bind:value={delayMs} min="200" step="100" />
				ms
			</label>
			<button class="btn-secondary" on:click={resetFeeder}>Reset feeder</button>
		</div>
	</section>
</div>
