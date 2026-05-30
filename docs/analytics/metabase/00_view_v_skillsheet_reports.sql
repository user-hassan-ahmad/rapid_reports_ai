-- Canonical analysis model for skill-sheet report analytics.
-- ONE place that encodes scope (organic users + skill-sheet pipelines) and joins
-- report + pipeline + skill sheet + quality scores + latest audit + acceptance signals.
-- Every Metabase question should build on this view so scope can never drift.
--
-- Apply (idempotent):  psql "$DATABASE_PUBLIC_URL" -f 00_view_v_skillsheet_reports.sql
--
-- Quality scoring: prefers rubric v2 (dictation_fidelity + normal_fill_appropriateness;
-- sheet_fit retired) and falls back to v1 per report. input_faithfulness is kept as a
-- back-compat alias for the strict fidelity dimension (= dictation_fidelity in v2).
-- quality_core = mean(output_adherence, fidelity) — the cross-pipeline comparable quality.

CREATE OR REPLACE VIEW v_skillsheet_reports AS
WITH latest_audit AS (
  SELECT DISTINCT ON (report_id) report_id, overall_status
  FROM report_audits
  ORDER BY report_id, created_at DESC
)
SELECT
  r.id                                   AS report_id,
  r.created_at,
  date_trunc('week', r.created_at)::date AS week,
  CASE WHEN r.report_type = 'auto' THEN 'quick' ELSE 'template' END AS pipeline,
  u.email                                AS user_email,
  COALESCE(ess.scan_type_normalized, lower(t.name)) AS scan_type,
  ess.analyser_model,
  ess.analyser_latency_ms,
  ess.analyser_prompt_version,
  t.name                                 AS template_name,
  q.sheet_fit,
  q.output_adherence,
  COALESCE(q.dictation_fidelity, q.input_faithfulness) AS input_faithfulness,  -- strict fidelity (v2 or v1)
  q.dictation_fidelity,
  q.normal_fill_appropriateness,
  q.edit_burden,
  CASE WHEN q.output_adherence IS NOT NULL
        AND COALESCE(q.dictation_fidelity, q.input_faithfulness) IS NOT NULL
       THEN round((q.output_adherence + COALESCE(q.dictation_fidelity, q.input_faithfulness)) / 2.0, 2)
  END                                    AS quality_core,
  q.judge_model,
  q.rubric_version,
  la.overall_status                      AS audit_status,
  (r.final_report_content IS NOT NULL)   AS has_final_edit,
  EXISTS (SELECT 1 FROM report_feedback f WHERE f.report_id = r.id AND f.lifecycle = 'copied') AS was_copied
FROM reports r
JOIN users u ON u.id = r.user_id AND lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
LEFT JOIN ephemeral_skill_sheets ess ON ess.id = r.ephemeral_skill_sheet_id
LEFT JOIN templates t ON t.id = r.template_id
LEFT JOIN LATERAL (
  -- prefer the v2 score row, fall back to v1
  SELECT * FROM report_quality_scores s
  WHERE s.report_id = r.id
  ORDER BY CASE s.rubric_version WHEN 'v2' THEN 2 WHEN 'v1' THEN 1 ELSE 0 END DESC
  LIMIT 1
) q ON true
LEFT JOIN latest_audit la ON la.report_id = r.id
WHERE (r.report_type = 'auto' AND r.generation_mode = 'quick_ephemeral')
   OR (r.report_type = 'templated' AND t.template_config->>'generation_mode' = 'skill_sheet_guided');
