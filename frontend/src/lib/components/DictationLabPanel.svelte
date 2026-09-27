<script lang="ts">
	import { onDestroy } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { labConfig } from '$lib/dictation-lab/labConfig';
	import { buildFixtureLine, suggestId } from '$lib/dictation-lab/fixtureExport';
	import { buildCoverageFixtureLine, coverageAgreement } from '$lib/dictation-lab/coverage';
	import { derivePlacement } from '$lib/dictation-lab/frontDoor';
	import { agreementClass, summariseTraces, type AgreementClass } from '$lib/dictation-lab/summary';
	import {
		FAST_ROUTES,
		buildSessionExport,
		summariseDecisions,
		type DecisionRecord,
		type OutcomeEvent
	} from '$lib/dictation-lab/decisionFirst';
	import {
		TRIAGE_ACTIONS,
		type ChunkTrace,
		type CoverageTrace,
		type FixtureCase,
		type ProcessTrace,
		type TriageAction,
		type TriageCandidateTrace
	} from '$lib/dictation-lab/types';

	/** Feeds one utterance into the production scratchpad (IntelliDictateTab.injectTranscript). */
	export let inject: (text: string) => void = () => {};
	export let traces: ProcessTrace[] = [];
	export let onClear: () => void = () => {};
	export let coverageTrace: CoverageTrace | null = null;
	export let chunkTraces: ChunkTrace[] = [];
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

	// ── Front door ─────────────────────────────────────────────────────────────
	let boundaryBuffer = '';
	let boundarySeq = 1;
	$: chunkSummary = {
		chunks: chunkTraces.filter((c) => !c.viaBackstop && c.silence_s == null).length,
		rechecks: chunkTraces.filter((c) => c.silence_s != null && !c.viaBackstop).length,
		sent: chunkTraces.filter((c) => c.sent !== null).length,
		backstops: chunkTraces.filter((c) => c.viaBackstop).length,
		placement: (() => {
			// Shadow-compare Jev's placement with what the polish did, matched on the sent text.
			let n = 0, agree = 0;
			for (const c of chunkTraces) {
				if (!c.sent || !c.placement) continue;
				const p = traces.find((t) => t.utterance === c.sent);
				if (!p) continue;
				const d = derivePlacement(p.activeBefore, p.activeAfter);
				if (!d) continue;
				n += 1;
				if (d === c.placement) agree += 1;
			}
			return { n, agree };
		})(),
		meanLatency: (() => {
			const xs = chunkTraces.filter((c) => !c.viaBackstop && c.silence_s == null).map((c) => c.latency_ms);
			return xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null;
		})()
	};
	function addBoundaryFixture(c: ChunkTrace, expected: string): void {
		const line = JSON.stringify({
			id: `lab-bnd-${String(boundarySeq++).padStart(2, '0')}`,
			scan_type: coverageState?.scanType ?? '',
			buffered: c.buffered,
			chunk: c.chunk,
			scratchpad_tail: '',
			expected_boundary: expected,
			expected_asr_risk: (c.asr_risk ?? 0) >= 0.5,
			hard: false,
			note: 'from lab'
		});
		boundaryBuffer = boundaryBuffer ? `${boundaryBuffer}\n${line}` : line;
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
	let fixtureNote = '';

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

	async function loadFixtures(): Promise<void> {
		fixtureNote = '';
		try {
			const headers: Record<string, string> = {};
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/triage/fixtures`, { headers });
			if (!res.ok) {
				fixtureNote = `fixtures unavailable (${res.status}) — is RR_TRIAGE_DEBUG=1 on the backend?`;
				return;
			}
			const data = (await res.json()) as { cases: FixtureCase[] };
			feederText = data.cases.map((c) => c.utterance).join('\n');
			cursor = 0;
			fixtureNote = `${data.cases.length} fixture utterances loaded (state is whatever the scratchpad holds now)`;
		} catch (e) {
			fixtureNote = `fixtures failed: ${(e as Error).message}`;
		}
	}

	// ── Timeline ───────────────────────────────────────────────────────────────
	let expanded: number | null = null;
	const CLASS_STYLE: Record<AgreementClass, string> = {
		none: 'border-gray-700',
		deterministic: 'border-blue-500',
		both: 'border-emerald-500',
		one: 'border-amber-500',
		neither: 'border-red-500'
	};
	function fmtCand(c: TriageCandidateTrace | null): string {
		if (!c) return '—';
		if (c.error) return `error:${c.error}`;
		const conf = c.confidence == null ? '' : ` ${c.confidence.toFixed(2)}`;
		return `${c.action}${conf} · ${c.latency_ms ?? '?'}ms`;
	}
	$: summary = summariseTraces(traces);

	// ── Export ─────────────────────────────────────────────────────────────────
	let exportBuffer = '';
	let exportSeq = 1;
	let exporting: ProcessTrace | null = null;
	let exp = {
		expected_action: 'append_new_finding' as TriageAction,
		expected_is_correction: false,
		expected_needs_committed_edit: false,
		hard: false,
		note: ''
	};

	function startExport(p: ProcessTrace): void {
		exporting = p;
		const guess = (p.triage?.jev?.action ?? p.triage?.qwen?.action ?? 'append_new_finding') as TriageAction;
		exp = {
			expected_action: guess,
			expected_is_correction: guess === 'correct_previous_finding' || guess === 'delete_previous_utterance',
			expected_needs_committed_edit: false,
			hard: false,
			note: ''
		};
	}
	function confirmExport(): void {
		if (!exporting) return;
		const line = buildFixtureLine(exporting, { id: suggestId(exp.expected_action, exportSeq++), ...exp });
		exportBuffer = exportBuffer ? `${exportBuffer}\n${line}` : line;
		exporting = null;
	}
	async function copyBuffer(): Promise<void> {
		try {
			await navigator.clipboard.writeText(exportBuffer);
		} catch {
			/* clipboard may be blocked; the textarea is selectable */
		}
	}
</script>

<div class="space-y-4 text-sm">
	<!-- Strategy -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">Strategy</h3>
		<div class="flex flex-wrap gap-3">
			{#each [['shadow', 'observe'], ['route:jev', 'route on Jev'], ['route:qwen', 'route on Qwen']] as [value, label]}
				<label class="flex items-center gap-1">
					<input type="radio" bind:group={$labConfig.strategy} {value} />
					{label}
				</label>
			{/each}
		</div>
		<label class="flex items-center gap-2">
			threshold
			<input
				type="range"
				min="0.5"
				max="1"
				step="0.05"
				bind:value={$labConfig.threshold}
				disabled={$labConfig.strategy === 'route:qwen'}
			/>
			<span class="tabular-nums">{$labConfig.threshold.toFixed(2)}</span>
			{#if $labConfig.strategy === 'route:qwen'}
				<span class="text-gray-400">(Qwen has no confidence; always routes)</span>
			{/if}
		</label>
		<div class="flex flex-wrap gap-3">
			<span class="text-gray-400">front door</span>
			{#each [['timer', 'silence timers'], ['jev', 'Jev boundary'], ['decision', 'decision-first (live)']] as [value, label]}
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
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={$labConfig.showBoth} />
			show both candidates (triage_debug)
		</label>
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
						{#if d.rec.line_closed_by}<span class="text-violet-300">⏎ {d.rec.line_closed_by}</span>{/if}
						{#if k}{#each [...k] as kind}<span class="text-red-300">{kind}</span>{/each}{/if}
						{#if d.rec.error}<span class="text-red-300">{d.rec.error}</span>{/if}
					</div>
				{/each}
			</div>
		</section>
	{/if}

	<!-- Chunks (front door) -->
	{#if $labConfig.frontDoor === 'jev' || chunkTraces.length > 0}
		<section class="card-dark space-y-1">
			<h3 class="font-semibold">
				Chunks
				<span class="text-gray-400 font-normal text-xs">
					{chunkSummary.chunks} chunks · {chunkSummary.sent} sent · {chunkSummary.chunks - chunkSummary.sent} polish calls saved
					· {chunkSummary.rechecks} silence re-checks · {chunkSummary.backstops} hard limit · mean {chunkSummary.meanLatency ?? '—'} ms
					· placement agrees {chunkSummary.placement.agree}/{chunkSummary.placement.n}
				</span>
			</h3>
			<div class="max-h-56 overflow-y-auto space-y-0.5">
				{#each chunkTraces as c (c.seq)}
					<div class="text-xs flex flex-wrap gap-x-2 items-baseline border-l-2 pl-2 {c.sent !== null ? 'border-emerald-500/60' : 'border-gray-700'}">
						<span class="font-mono truncate max-w-[14rem]">“{c.viaBackstop ? c.buffered : c.chunk}”</span>
						{#if c.silence_s != null && !c.viaBackstop}<span class="text-violet-300">silence {c.silence_s}s{c.standalone != null ? ` · standalone ${c.standalone.toFixed(2)}` : ''} →</span>{/if}
						<span class={c.resolved === 'continues' ? 'text-gray-400' : c.resolved === 'command' ? 'text-blue-300' : 'text-emerald-300'}>{c.viaBackstop ? 'hard limit' : c.resolved}{c.via === 'punctuation' ? ' (punct.)' : c.via === 'silence' && c.resolved === 'complete' ? ' (silence)' : ''}</span>
						{#if c.boundary && c.boundary !== c.resolved && !c.viaBackstop}<span class="text-gray-500">jev: {c.boundary}</span>{/if}
						{#if c.confidence != null}<span class="tabular-nums text-gray-400">{c.confidence.toFixed(2)}</span>{/if}
						{#if c.asr_risk != null && c.asr_risk >= 0.5}<span class="text-amber-300">asr {c.asr_risk.toFixed(2)}</span>{/if}
						<span class="tabular-nums text-gray-500">{c.latency_ms} ms</span>
						{#if c.placement}
							{@const p = traces.find((t) => t.utterance === c.sent)}
							{@const d = p ? derivePlacement(p.activeBefore, p.activeAfter) : null}
							<span class={d == null ? 'text-gray-500' : d === c.placement ? 'text-emerald-300' : 'text-amber-300'}>
								{c.placement.replace(/_/g, ' ')}{c.placement_confidence != null ? ` ${c.placement_confidence.toFixed(2)}` : ''}{d && d !== c.placement ? ` (polish: ${d.replace(/_/g, ' ')})` : ''}
							</span>
						{/if}
						{#if c.error}<span class="text-red-300">{c.error}</span>{/if}
						{#if !c.viaBackstop}
							<span class="ml-auto flex gap-1">
								{#each ['complete', 'continues', 'command'] as b}
									<button class="text-[10px] text-gray-500 underline" on:click={() => addBoundaryFixture(c, b)}>{b[0]}</button>
								{/each}
							</span>
						{/if}
					</div>
				{/each}
			</div>
			{#if boundaryBuffer}
				<textarea class="w-full h-16 bg-gray-900 rounded p-2 font-mono text-xs" readonly value={boundaryBuffer}></textarea>
				<p class="text-[10px] text-gray-500">→ backend/tests/fixtures/boundary_cases.jsonl (fill scratchpad_tail and note by hand)</p>
			{/if}
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
			<button class="btn-secondary" on:click={loadFixtures}>Load fixtures</button>
		</div>
		{#if fixtureNote}<p class="text-gray-400">{fixtureNote}</p>{/if}
	</section>

	<!-- Summary -->
	<section class="card-dark grid grid-cols-2 gap-x-4 gap-y-1">
		<h3 class="font-semibold col-span-2">
			Session
			<button class="text-xs text-gray-400 underline ml-2" on:click={onClear}>clear timeline</button>
		</h3>
		<span>calls</span><span class="tabular-nums">{summary.total}</span>
		<span>deterministic / model</span><span class="tabular-nums">{summary.deterministic} / {summary.model}</span>
		<span>mean latency deterministic</span><span class="tabular-nums">{summary.meanLatencyDeterministicMs ?? '—'} ms</span>
		<span>mean latency model</span><span class="tabular-nums">{summary.meanLatencyModelMs ?? '—'} ms</span>
		<span>Jev agreement</span><span class="tabular-nums">{summary.agreement.jev.agreed}/{summary.agreement.jev.n}</span>
		<span>Qwen agreement</span><span class="tabular-nums">{summary.agreement.qwen.agreed}/{summary.agreement.qwen.n}</span>
	</section>

	<!-- Timeline -->
	<section class="card-dark space-y-1 max-h-[28rem] overflow-y-auto">
		<h3 class="font-semibold">Timeline</h3>
		{#if traces.length === 0}<p class="text-gray-400">No calls yet. Dictate or use the feeder.</p>{/if}
		{#each traces as p (p.seq)}
			{@const cls = agreementClass(p)}
			<div class="border-l-4 pl-2 py-1 {CLASS_STYLE[cls]}">
				<button class="text-left w-full" on:click={() => (expanded = expanded === p.seq ? null : p.seq)}>
					<div class="flex justify-between gap-2">
						<span class="font-mono truncate">#{p.seq} “{p.utterance || '(no delta)'}”</span>
						<span class="tabular-nums text-gray-400">{p.latency_ms} ms</span>
					</div>
					<div class="text-xs text-gray-300">
						derived={p.triage?.derived ?? '—'} · routed={p.triage?.routed ?? '—'}{p.triage?.routed_by
							? ` by ${p.triage.routed_by}`
							: ''}
						· jev: {fmtCand(p.triage?.jev ?? null)} · qwen: {fmtCand(p.triage?.qwen ?? null)}
					</div>
				</button>
				{#if expanded === p.seq}
					<pre class="text-xs bg-gray-900 rounded p-2 overflow-x-auto">{JSON.stringify(p, null, 1)}</pre>
					<button class="btn-secondary text-xs" on:click={() => startExport(p)}>Add to fixtures</button>
				{/if}
			</div>
		{/each}
	</section>

	<!-- Export form -->
	{#if exporting}
		<section class="card-dark space-y-2 border border-amber-500/50">
			<h3 class="font-semibold">Label #{exporting.seq}: “{exporting.utterance}”</h3>
			<label class="block">
				expected action
				<select class="bg-gray-900 rounded px-1 ml-2" bind:value={exp.expected_action}>
					{#each TRIAGE_ACTIONS as a}<option value={a}>{a}</option>{/each}
				</select>
			</label>
			<label class="flex items-center gap-2">
				<input type="checkbox" bind:checked={exp.expected_is_correction} /> is_correction
			</label>
			<label class="flex items-center gap-2">
				<input type="checkbox" bind:checked={exp.expected_needs_committed_edit} /> needs_committed_edit
			</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:checked={exp.hard} /> hard</label>
			<input class="w-full bg-gray-900 rounded px-2 py-1" placeholder="note" bind:value={exp.note} />
			<div class="flex gap-2">
				<button class="btn-primary" on:click={confirmExport}>Append line</button>
				<button class="btn-secondary" on:click={() => (exporting = null)}>Cancel</button>
			</div>
		</section>
	{/if}

	<section class="card-dark space-y-2">
		<h3 class="font-semibold">
			Fixture buffer
			<span class="text-gray-400 font-normal">→ paste into backend/tests/fixtures/triage_utterances.jsonl</span>
		</h3>
		<textarea class="w-full h-24 bg-gray-900 rounded p-2 font-mono text-xs" readonly value={exportBuffer}></textarea>
		<button class="btn-secondary" on:click={copyBuffer} disabled={!exportBuffer}>Copy fixtures</button>
	</section>
</div>
