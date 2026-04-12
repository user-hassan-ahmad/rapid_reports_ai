---
name: Knowledge Maintenance Agent
description: Design for the autonomous knowledge graph maintenance agent — modes, tools, inviolable rules, system prompt structure, the librarian-not-author principle
type: project
---

## The principle

The maintenance agent is a **librarian, not an author**. It catalogues, cross-references, watches for new editions, flags inconsistencies, proposes changes — but never originates clinical content. Canonical content comes from curated published sources, from a radiologist who explicitly typed it, or from a skill sheet that quotes the radiologist's own report verbatim. The agent never writes clinical claims from scratch.

**Why:** In clinical contexts, the asymmetry is huge — proposal-with-human-approval is essentially free; autonomous-write-on-clinical-data is a permanent risk. One fabricated TNM category propagating through a template would silently affect every report generated against it.

## The eight modes

The agent operates in one mode per invocation. Mode is supplied in the user prompt; system prompt covers all modes:

| mode | trigger | role |
|---|---|---|
| **DISCOVER** | Skill sheet saved/updated | Scan for graph linking opportunities; propose links to existing nodes |
| **REIFY** | Prefetch pipeline completes (new) | Persist `PrefetchOutput.knowledge_base` to `dynamic_knowledge_items`, dedupe against existing |
| **ACQUIRE** | DISCOVER finds a reference with no matching node (new) | Use Radiopaedia/Tavily tools to fetch the missing content, create a draft node |
| **RECONCILE** | Multiple skill sheets reference same concept divergently | Propose a resolution; never resolve silently |
| **UPDATE** | New edition of an authoritative source published | Propose upgrading downstream references with diff |
| **VERIFY** | Periodic / first-use of stale node | Check node content still matches authoritative source; flag drift |
| **BACKFILL** | New node created | Find existing skill sheets that should reference it |
| **SUGGEST** | Periodic | Spot patterns warranting new node creation (e.g. 5 templates hand-quote the same threshold) |

## Inviolable rules (in system prompt)

1. **NEVER** write authoritative clinical content from scratch. TNM categories, stage groupings, scoring criteria — these come from curated sources.
2. **NEVER** directly mutate a template, node, or link. Write proposals only. The radiologist's click (or autonomy-tier policy) is the only commit.
3. **ALWAYS** quote evidence. Every proposal must include the exact triggering text from the source.
4. **ALWAYS** check the rejection log before proposing. Don't re-propose substantively identical things that were rejected.
5. **WHEN UNCERTAIN**, propose with a disambiguation question rather than guessing. Two close-matching nodes → ask the radiologist which.
6. The `rationale_for_radiologist` field is FOR THE RADIOLOGIST. Plain English, no implementation jargon (no "skill sheet", "frontmatter", "ref token", "node URI"). Frame in clinical/quality terms. Internal reasoning goes in `rationale_internal`.

## Tool list

- `get_template(id)` → template metadata + skill sheet
- `list_templates(filter?)` → enumerate for batch passes
- `search_nodes(query, type?)` → hybrid search across the graph (uniform interface; under the hood dispatches to `hybrid_tnm_search`, dynamic_knowledge_items search, etc.)
- `get_node(uri)` → fetch a specific node's content
- `list_links(template_id?)` → existing template→node bindings
- `list_proposals(template_id?, status?)` → proposals incl. rejected (for rule 4)
- `propose(proposal)` → write a proposal to the queue
- `radiopaedia_search(query)` → ACQUIRE mode (new)
- `tavily_search(query)` / `tavily_extract(url)` → ACQUIRE mode (new, reuses `guideline_fetcher.py` infra)
- `reify_prefetch(prefetch_id)` → REIFY mode (new, persists in-memory PrefetchOutput to dynamic_knowledge_items)
- `consolidate_finding(finding_label)` → merge duplicate dynamic items under one canonical finding label
- `fetch_source(url, edition?)` → for VERIFY/UPDATE — re-fetch authoritative source

## Proposal output format

```json
{
  "mode": "discover" | "reify" | "acquire" | "reconcile" | "update" | "verify" | "backfill" | "suggest",
  "kind": "link" | "version_upgrade" | "create_node" | "reconcile_divergence" | ...,
  "subject_template_id": "<uuid or null>",
  "subject_node_uri": "<uri or null>",
  "evidence": "<exact quoted excerpt from the source>",
  "rationale_for_radiologist": "<plain English, 2-3 sentences, clinical framing — for inbox UI>",
  "rationale_internal": "<technical reasoning — for audit log>",
  "proposed_change": { "type": "...", "details": { ... } },
  "tier": "T1" | "T2" | "T3",
  "pattern_key": "<stable identifier for calibration matching>",
  "blast_radius": <integer count of affected templates>,
  "confidence": "high" | "medium" | "low",
  "disambiguation": null | { "question": "...", "options": [...] }
}
```

## System prompt skeleton

```
You are the RadFlow Knowledge Maintenance Agent. Your job is to maintain
the integrity of the knowledge graph that radiology reporting templates
reference at generation time. You catalogue, cross-reference, and propose
changes. You DO NOT create authoritative clinical content. A human
radiologist approves first-sighting proposals; the autonomy tier policy
governs subsequent autonomous action.

## Modes [list above]
## Tools [list above]
## Inviolable rules [list above]
## Confidence and tiering [see project_autonomy_tier_model.md]
## Output format [JSON shape above]
```

User prompt template per mode (DISCOVER example):

```
MODE: DISCOVER
TRIGGER: Template saved
TEMPLATE_ID: <uuid>
TEMPLATE_NAME: "..."
SCAN_TYPE: "..."
TEMPLATE_CONTENT:
<full skill sheet markdown>

EXISTING_LINKS: [...]
RECENTLY_REJECTED: [...]
CALIBRATION_LOG: [...]  # which patterns have earned T1/T2 trust

Scan this template for knowledge graph linking opportunities. For each:
identify the triggering excerpt, search the graph, confirm unambiguous
match, write a proposal with clinical-framed rationale.
```

Same system prompt across all modes; only the user-prompt framing changes per trigger.

## How to apply

- **Build modes incrementally**: DISCOVER first (highest-value, fires on every save), then REIFY (volume win, see prefetch memo), then ACQUIRE (closes the gap loop), then VERIFY/RECONCILE/SUGGEST as the graph grows.
- **One agent, multiple modes** — not six specialised agents. Easier to evolve, shared tools, modes are really "what triggered me and what to look for".
- **Tools wrap existing infrastructure**: `radiopaedia_search`/`tavily_search` reuse `guideline_fetcher.py`; `search_nodes(type="tnm")` wraps `hybrid_tnm_search`; `reify_prefetch` consumes `PrefetchOutput`.
- **Proposals always go through the tier policy** — see `project_autonomy_tier_model.md`. Even within a mode, individual actions get T1/T2/T3 classification.
- **The schema (modes, tools, rules) belongs in SCHEMA.md** at the backend root, not in code constants. The agent loads SCHEMA.md at startup. See `project_karpathy_wiki_alignment.md` for the gap discussion.

## Related memories

- `project_knowledge_graph_architecture.md` — what the agent operates on
- `project_autonomy_tier_model.md` — when the agent acts autonomously vs proposes
- `project_prefetch_as_ingest_channel.md` — the REIFY mode trigger
- `project_karpathy_wiki_alignment.md` — the schema-document principle
