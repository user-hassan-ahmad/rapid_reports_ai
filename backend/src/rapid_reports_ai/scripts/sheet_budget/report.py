"""Emit the quality-vs-tokens curve as CSV and as a self-contained HTML page.

Latency projections cover the self-hosted target band (100/115/130 tok/s
decode). Measured generator wall time is rescaled from the Groq rate; the
projection assumes reasoning volume is unchanged at a given budget, so it is
a floor rather than a forecast.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

DIMS = ("output_adherence", "dictation_fidelity",
        "normal_fill_appropriateness", "unwarranted_assertion")
THROUGHPUTS = (100, 115, 130)
GROQ_RATE = 450  # measured effective decode rate, 2026-08-12 bake-off


def _mean_score(run: dict) -> float | None:
    j = run.get("judge")
    if not j:
        return None
    scores = [j[d]["score"] for d in DIMS if d in j]
    return round(sum(scores) / len(scores), 2) if scores else None


def write_curve_csv(runs: list[dict], path: Path) -> None:
    fields = ["tier", "case", "sheet_chars", "sheet_tokens_est", "report_chars",
              "analyser_latency_ms", "generator_latency_ms", "gate_passed",
              "gate_failures", "mean_score", *DIMS]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in runs:
            row = {k: r.get(k) for k in fields}
            g = r.get("gate") or {}
            row["gate_passed"] = g.get("passed")
            row["gate_failures"] = "|".join(g.get("failures", []))
            row["mean_score"] = _mean_score(r)
            for d in DIMS:
                row[d] = (r.get("judge") or {}).get(d, {}).get("score")
            w.writerow(row)


def write_artifact_html(runs: list[dict], path: Path) -> None:
    points = [
        {"tier": r["tier"], "case": r.get("case"), "x": r.get("sheet_tokens_est"),
         "y": _mean_score(r), "gate": (r.get("gate") or {}).get("passed"),
         "gen_ms": r.get("generator_latency_ms"),
         "dims": {d: (r.get("judge") or {}).get(d, {}).get("score") for d in DIMS}}
        for r in runs if r.get("sheet_tokens_est") is not None
    ]
    path.write_text(
        _HTML.replace("{{DATA}}", json.dumps(points))
             .replace("{{THROUGHPUTS}}", json.dumps(list(THROUGHPUTS)))
             .replace("{{GROQ_RATE}}", str(GROQ_RATE))
             .replace("{{DIMS}}", json.dumps(list(DIMS)))
    )


_HTML = """<title>Qwen sheet-budget — quality vs tokens</title>
<style>
  :root { --bg:#fff; --fg:#1a1a1a; --muted:#666; --grid:#e5e5e5; --pass:#2563eb; --fail:#dc2626; --card:#f7f7f8; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
    --bg:#111; --fg:#eee; --muted:#999; --grid:#333; --pass:#60a5fa; --fail:#f87171; --card:#1b1b1d; } }
  :root[data-theme="dark"] { --bg:#111; --fg:#eee; --muted:#999; --grid:#333; --pass:#60a5fa; --fail:#f87171; --card:#1b1b1d; }
  body { background:var(--bg); color:var(--fg); margin:0; padding:2rem 1.25rem;
         font:15px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif; }
  .wrap { max-width:920px; margin:0 auto; }
  h1 { font-size:1.5rem; margin:0 0 .35rem; letter-spacing:-.01em; }
  h2 { font-size:1.05rem; margin:2rem 0 .5rem; }
  table { border-collapse:collapse; width:100%; font-size:14px; }
  th,td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--grid); white-space:nowrap; }
  th { font-weight:600; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  .fail { color:var(--fail); font-weight:600; }
  .pass { color:var(--pass); }
  p.note { color:var(--muted); margin:.3rem 0 1rem; }
  figure { margin:0 0 1rem; background:var(--card); border-radius:10px; padding:1rem; }
  svg { display:block; width:100%; height:auto; }
</style>
<div class="wrap">
<h1>Qwen 3.6 27B — sheet budget vs report quality</h1>
<p class="note">Mean rubric v2.2 score against achieved skill-sheet size. Runs that failed the
structural gate are red and excluded from the quality reading — a failed tier is a result,
not a gap.</p>
<figure>
<svg id="chart" viewBox="0 0 720 380" role="img" aria-label="Mean judge score versus achieved sheet tokens"></svg>
</figure>
<div class="scroll"><table id="tbl"><thead><tr>
<th>Tier</th><th>Case</th><th>Sheet tok</th><th>Mean</th><th>Gen</th><th>Gate</th>
</tr></thead><tbody></tbody></table></div>
<h2>Per-dimension means by tier</h2>
<p class="note">Which dimension degrades first identifies the mechanism.</p>
<div class="scroll"><table id="dims"><thead></thead><tbody></tbody></table></div>
<h2>Projected self-hosted generate latency</h2>
<p class="note">Measured generator wall time rescaled from the Groq rate ({{GROQ_RATE}} tok/s)
to the self-hosted decode band. A floor, not a forecast: it assumes reasoning volume is
unchanged at a given budget.</p>
<div class="scroll"><table id="proj"><thead><tr><th>Tier</th><th>Groq (measured)</th><th>@100 t/s</th><th>@115 t/s</th><th>@130 t/s</th></tr></thead><tbody></tbody></table></div>
</div>
<script>
const DATA = {{DATA}}, TP = {{THROUGHPUTS}}, GROQ = {{GROQ_RATE}}, DIMS = {{DIMS}};
const median = a => { const s=[...a].sort((x,y)=>x-y); return s[Math.floor(s.length/2)]; };

const tb = document.querySelector('#tbl tbody');
DATA.forEach(d => {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${d.tier}</td><td>${d.case ?? ''}</td>
    <td>${d.x != null ? d.x.toLocaleString() : '—'}</td>
    <td>${d.y ?? '—'}</td>
    <td>${d.gen_ms ? (d.gen_ms/1000).toFixed(1)+'s' : '—'}</td>
    <td class="${d.gate ? 'pass' : 'fail'}">${d.gate ? 'pass' : 'FAIL'}</td>`;
  tb.appendChild(tr);
});

const tiers = [...new Set(DATA.map(d => d.tier))];
const dh = document.querySelector('#dims thead'), db = document.querySelector('#dims tbody');
dh.innerHTML = '<tr><th>Tier</th>' + DIMS.map(d => `<th>${d.replace(/_/g,' ')}</th>`).join('') + '</tr>';
tiers.forEach(t => {
  const rows = DATA.filter(d => d.tier === t && d.y != null);
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${t}</td>` + DIMS.map(dim => {
    const vals = rows.map(r => r.dims && r.dims[dim]).filter(v => v != null);
    return `<td>${vals.length ? (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(2) : '—'}</td>`;
  }).join('');
  db.appendChild(tr);
});

const pb = document.querySelector('#proj tbody');
tiers.forEach(t => {
  const arr = DATA.filter(d => d.tier === t && d.gen_ms).map(d => d.gen_ms/1000);
  if (!arr.length) return;
  const med = median(arr);
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${t}</td><td>${med.toFixed(1)}s</td>` +
    TP.map(x => `<td>${(med * GROQ / x).toFixed(1)}s</td>`).join('');
  pb.appendChild(tr);
});

const pts = DATA.filter(d => d.y != null && d.x != null);
const svg = document.getElementById('chart');
if (pts.length) {
  const P = {l:52,r:24,t:18,b:46}, W=720, H=380;
  const xmax = Math.max(...pts.map(p=>p.x)) * 1.08;
  const X = v => P.l + v/xmax * (W-P.l-P.r);
  const Y = v => H-P.b - (v-1)/4 * (H-P.t-P.b);
  let s = '';
  for (let v=1; v<=5; v++) {
    s += `<line x1="${P.l}" y1="${Y(v)}" x2="${W-P.r}" y2="${Y(v)}" stroke="var(--grid)"/>`;
    s += `<text x="${P.l-10}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="12">${v}</text>`;
  }
  // tier means, joined - this is the curve whose knee we are looking for
  const means = tiers.map(t => {
    const r = pts.filter(p => p.tier === t);
    if (!r.length) return null;
    return {t, x: r.reduce((a,b)=>a+b.x,0)/r.length, y: r.reduce((a,b)=>a+b.y,0)/r.length};
  }).filter(Boolean).sort((a,b)=>a.x-b.x);
  if (means.length > 1) {
    s += `<polyline fill="none" stroke="var(--pass)" stroke-width="2" opacity=".55" points="${
      means.map(m => `${X(m.x)},${Y(m.y)}`).join(' ')}"/>`;
  }
  pts.forEach(p => {
    s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4.5" fill="${p.gate ? 'var(--pass)' : 'var(--fail)'}"
      opacity=".75"><title>${p.tier} ${p.case}: ${p.y}</title></circle>`;
  });
  means.forEach(m => {
    s += `<circle cx="${X(m.x)}" cy="${Y(m.y)}" r="6" fill="none" stroke="var(--pass)" stroke-width="2"/>`;
    s += `<text x="${X(m.x)}" y="${Y(m.y)-14}" text-anchor="middle" fill="var(--fg)" font-size="12"
      font-weight="600">${m.t}</text>`;
  });
  s += `<text x="${W/2}" y="${H-10}" text-anchor="middle" fill="var(--muted)" font-size="12">achieved skill-sheet tokens</text>`;
  svg.innerHTML = s;
} else {
  svg.innerHTML = `<text x="360" y="190" text-anchor="middle" fill="var(--muted)" font-size="13">No judged runs yet</text>`;
}
</script>
"""
