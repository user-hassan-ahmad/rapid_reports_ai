-- ============================================================================
-- Metabase SQL pack — TRACE + LLM QUALITY
-- REQUIRES: the report_quality_scores migration applied AND the batch scorer run
-- (scripts/score_report_quality.py). Before that, the LLM-score columns are NULL.
-- ============================================================================


-- ===== Q8: Per-report trace (input -> sheet -> output -> final + scores) =====
-- Becomes a Metabase Table. Click a row for the full skill sheet / outputs and
-- the rationale (dimensions_json). Scope: organic + skill-sheet pipelines.
WITH excluded(e) AS (VALUES (lower('hassan.ahmad.ucl@gmail.com')))
SELECT r.id AS report_id,
       CASE WHEN r.report_type='auto' THEN 'quick' ELSE 'template' END AS pipeline,
       r.created_at,
       ess.scan_type,
       ess.clinical_history,
       COALESCE(ess.skill_sheet_markdown, t.template_config->>'skill_sheet') AS skill_sheet,
       r.report_content AS ai_output,
       COALESCE(r.final_report_content, rf.final_output) AS final_output,
       q.edit_burden,
       q.sheet_fit,
       q.output_adherence,
       q.input_faithfulness,
       q.dimensions_json
FROM reports r
JOIN users u ON u.id = r.user_id AND lower(u.email) NOT IN (SELECT e FROM excluded)
LEFT JOIN ephemeral_skill_sheets ess ON ess.id = r.ephemeral_skill_sheet_id
LEFT JOIN templates t ON t.id = r.template_id
LEFT JOIN LATERAL (
    SELECT final_output FROM report_feedback f
    WHERE f.report_id = r.id ORDER BY updated_at DESC LIMIT 1
) rf ON true
LEFT JOIN report_quality_scores q ON q.report_id = r.id
WHERE (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
   OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided')
ORDER BY r.created_at DESC;


-- ===== Q9a: Quality score averages by pipeline ==============================
SELECT pipeline,
       count(*) AS scored,
       round(avg(sheet_fit), 2)            AS avg_sheet_fit,
       round(avg(output_adherence), 2)     AS avg_output_adherence,
       round(avg(input_faithfulness), 2)   AS avg_input_faithfulness,
       round(avg(edit_burden)::numeric, 3) AS avg_edit_burden
FROM report_quality_scores
GROUP BY pipeline
ORDER BY pipeline;


-- ===== Q9b: Score distributions (one row per report; histogram in Metabase) =
SELECT report_id, pipeline, sheet_fit, output_adherence, input_faithfulness, edit_burden
FROM report_quality_scores;


-- ===== Q9c: Validation — scores vs edit_burden (scatter in Metabase) ========
-- Expectation: adherence/faithfulness should trend DOWN as edit_burden rises.
SELECT edit_burden, output_adherence, input_faithfulness, sheet_fit, pipeline
FROM report_quality_scores
WHERE edit_burden IS NOT NULL;
