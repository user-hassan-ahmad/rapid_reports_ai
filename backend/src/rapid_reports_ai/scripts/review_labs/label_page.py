# backend/src/rapid_reports_ai/scripts/review_labs/label_page.py
"""One self-contained HTML labelling page for every gate. Data is embedded; verdicts live in localStorage
and leave through "Copy my verdicts". Hidden blocks show only after the card's required fields are set."""
from __future__ import annotations

import html as _html
import json
from pathlib import Path
from typing import List

_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--card:#fff;--line:#e4e2dc;--accent:#2f5d8a;--mark:#ffe89a;--on:#2f5d8a;--onfg:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe6;--muted:#a3a29c;--card:#1f1f1d;--line:#34332f;--accent:#8db4dc;--mark:#5c4d12;--on:#8db4dc;--onfg:#111}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ecebe6;--muted:#a3a29c;--card:#1f1f1d;--line:#34332f;--accent:#8db4dc;--mark:#5c4d12;--on:#8db4dc;--onfg:#111}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
h1{font-size:17px;margin:0;flex:1 1 auto}main{max-width:980px;margin:0 auto;padding:12px 16px 80px}
section.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px;margin:12px 0}
section.card.done{border-left:4px solid var(--accent)}.meta{color:var(--muted);font-size:13px}
.block{margin:8px 0}.block b{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
pre{white-space:pre-wrap;word-wrap:break-word;font:14px/1.45 ui-monospace,Menlo,monospace;margin:4px 0;background:transparent}
mark{background:var(--mark);color:inherit}button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;padding:5px 10px;cursor:pointer;margin:2px}
button[aria-pressed="true"]{background:var(--on);color:var(--onfg);border-color:var(--on)}textarea{width:100%;min-height:54px;font:inherit;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
.fields{border-top:1px dashed var(--line);margin-top:10px;padding-top:8px}.hidden{opacity:.95;border-left:3px solid var(--muted);padding-left:8px}
#out{position:fixed;bottom:0;left:0;right:0;height:30vh}
</style></head><body>
<header><h1>__TITLE__</h1><span id="progress" class="meta"></span>
<label class="meta"><input type="checkbox" id="todo"> Unlabelled only</label>
<button id="copy">Copy my verdicts</button></header>
<main id="cards"></main><textarea id="out" readonly hidden></textarea>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
let S = {}; let lastDecided = null; try { S = JSON.parse(localStorage.getItem(D.storage_key) || '{}'); } catch (e) {}
const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function marked(text, hl) { let h = esc(text); for (const m of (hl || [])) { if (!m) continue; const e = esc(m); h = h.split(e).join('<mark>' + e + '</mark>'); } return h; }
function decided(id) { const v = S[id] || {}; return D.fields.filter(f => f.required).every(f => v[f.key] !== undefined && v[f.key] !== ''); }
function save() { try { localStorage.setItem(D.storage_key, JSON.stringify(S)); } catch (e) {} progress(); }
function progress() { const n = D.cards.filter(c => decided(c.id)).length; document.getElementById('progress').textContent = n + ' / ' + D.cards.length + ' labelled'; }
function setv(id, key, val, quiet) { S[id] = S[id] || {}; S[id][key] = val; S[id].at = new Date().toISOString(); lastDecided = id; save(); if (!quiet) render(); }
function blockHtml(b) { const body = '<pre>' + marked(b.text, b.highlight) + '</pre>';
  return '<div class="block"><b>' + esc(b.label) + '</b>' + (b.collapsed ? '<details><summary>show</summary>' + body + '</details>' : body) + '</div>'; }
function fieldHtml(c, f) { const v = (S[c.id] || {})[f.key];
  if (f.type === 'choice') return '<div><span class="meta">' + esc(f.label || f.key) + ': </span>' + f.options.map(o =>
    '<button aria-pressed="' + (v === o) + '" data-id="' + esc(c.id) + '" data-k="' + esc(f.key) + '" data-v="' + esc(o) + '">' + esc(o) + '</button>').join('') + '</div>';
  if (f.type === 'check') return '<label><input type="checkbox" data-id="' + esc(c.id) + '" data-k="' + esc(f.key) + '"' + (v ? ' checked' : '') + '> ' + esc(f.label || f.key) + '</label>';
  return '<div><span class="meta">' + esc(f.label || f.key) + '</span><textarea data-id="' + esc(c.id) + '" data-k="' + esc(f.key) + '">' + esc(v || '') + '</textarea></div>'; }
function render() { const todo = document.getElementById('todo').checked; const m = document.getElementById('cards');
  m.innerHTML = D.cards.filter(c => !todo || !decided(c.id) || c.id === lastDecided).map(c => '<section class="card' + (decided(c.id) ? ' done' : '') + '" id="card-' + esc(c.id) + '">' +
    '<div><strong>' + esc(c.title) + '</strong> <span class="meta">' + esc(c.meta || '') + '</span></div>' + c.blocks.map(blockHtml).join('') +
    '<div class="fields">' + D.fields.map(f => fieldHtml(c, f)).join('') + '</div>' +
    (decided(c.id) && (c.hidden || []).length ? '<div class="hidden">' + c.hidden.map(blockHtml).join('') + '</div>' : '') + '</section>').join('');
  progress(); }
document.addEventListener('click', e => { const b = e.target.closest('button[data-k]'); if (b) setv(b.dataset.id, b.dataset.k, b.dataset.v); });
document.addEventListener('change', e => { const t = e.target; if (!t.dataset || !t.dataset.k) return;
  if (t.type === 'checkbox') { if (t.id !== 'todo') setv(t.dataset.id, t.dataset.k, t.checked); } else setv(t.dataset.id, t.dataset.k, t.value, true); });
document.getElementById('todo').addEventListener('change', render);
document.getElementById('copy').addEventListener('click', () => { const json = JSON.stringify(S, null, 1); const out = document.getElementById('out');
  (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(() => { document.getElementById('copy').textContent = 'Copied ✓'; },
    () => { out.hidden = false; out.value = json; out.select(); }); });
render();
</script></body></html>
"""


def build_page(title: str, storage_key: str, cards: List[dict], fields: List[dict]) -> str:
    if not any(f.get("required") for f in fields):
        raise ValueError("at least one field must be required")
    ids = [c["id"] for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("card ids must be unique")
    data = json.dumps({"storage_key": storage_key, "cards": cards, "fields": fields}, ensure_ascii=False)
    data = data.replace("<", "\\u003c")
    return _TEMPLATE.replace("__TITLE__", _html.escape(title)).replace("__DATA__", data)


def write_page(path: Path, title: str, storage_key: str, cards: List[dict], fields: List[dict]) -> Path:
    path.write_text(build_page(title, storage_key, cards, fields))
    return path
