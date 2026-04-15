# Memory Index

## Active architecture (2026-04-11/12 design conversations)

- [Knowledge Graph Architecture](project_knowledge_graph_architecture.md) — Three node origins (static curated / dynamic prefetch / agent-acquired), resolver pattern with namespaced URIs, pre-resolved injection at generation time
- [Maintenance Agent](project_maintenance_agent.md) — Nine modes (DISCOVER/REIFY/ACQUIRE/RECONCILE/UPDATE/VERIFY/BACKFILL/SUGGEST/LEARN), inviolable rules, librarian-not-author principle
- [Autonomy Tier Model](project_autonomy_tier_model.md) — T1/T2/T3 with reversibility as safety net, calibration earned per pattern, decision-fatigue avoidance
- [Prefetch as Ingest Channel](project_prefetch_as_ingest_channel.md) — guideline_prefetch is the bulk knowledge source; currently DISCARDED; Iteration 5a unlock
- [Karpathy Wiki Alignment](project_karpathy_wiki_alignment.md) — How RadFlow maps to backend/llm-wiki.md, four gaps (SCHEMA.md, index, log, periodic lint)
- [Feedback Pipeline](project_feedback_pipeline.md) — Four-mechanism feedback (diff capture, thumbs up/down, N-use check-in, teach-me); "silent by default" UX principle

## Skill sheet system (current iteration)

- [Skill Sheet Template System](project_skill_sheet_system.md) — Status, recent commits, restructured iteration plan; production wizard already cut over to SkillSheetCreator
- [Global Style Guide Rules](project_global_style_guide.md) — Concrete rules from testing: voice, terminology, impression construction, fixed block params, clinical cross-referencing
- [Template Fidelity Audit](project_template_fidelity_audit.md) — New QA criterion + dedicated UI widget for skill-sheet conformance gaps
- [Parameter Slots](project_parameter_slots.md) — `{curly}` placeholders in skill sheets; resolves non-fabrication ↔ mandatory-structure tension via a third branch (emit slot verbatim when dictation is absent)
- [Reference Values Node](project_reference_values_node.md) — First concrete use case for promoted nodes; now subsumed by broader knowledge graph architecture
- [Feedback & Linting Design](project_feedback_linting_design.md) — Earlier partial analysis; now superseded by Feedback Pipeline spec
