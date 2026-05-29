-- ============================================================================
-- Metabase SQL pack — DESCRIPTIVE analytics (runnable today; no migration needed)
-- Scope (encoded in every query): organic users only (internal accounts excluded)
-- + skill-sheet pipelines only (quick_ephemeral + skill_sheet_guided templates).
-- Each delimited block is meant to become ONE Metabase Question.
-- Edit the excluded-email list if you add internal accounts.
-- ============================================================================


-- ===== Q1: Volume & adoption (reports per week x pipeline) ===================
WITH in_scope AS (
  SELECT r.*, CASE WHEN r.report_type='auto' THEN 'quick' ELSE 'template' END AS pipeline
  FROM reports r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN templates t ON t.id = r.template_id
  WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
    AND ( (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
       OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided') )
)
SELECT date_trunc('week', created_at)::date AS week, pipeline, count(*) AS reports
FROM in_scope
GROUP BY 1, 2
ORDER BY 1, 2;


-- ===== Q2: Adoption by user =================================================
WITH in_scope AS (
  SELECT r.*, u.email
  FROM reports r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN templates t ON t.id = r.template_id
  WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
    AND ( (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
       OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided') )
)
SELECT email,
       count(*) FILTER (WHERE report_type='auto')      AS quick,
       count(*) FILTER (WHERE report_type='templated')  AS template,
       count(*)                                         AS total
FROM in_scope
GROUP BY email
ORDER BY total DESC;


-- ===== Q3: Signal coverage (telemetry honesty) ==============================
WITH in_scope AS (
  SELECT r.*
  FROM reports r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN templates t ON t.id = r.template_id
  WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
    AND ( (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
       OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided') )
)
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE ephemeral_skill_sheet_id IS NOT NULL OR template_id IS NOT NULL) AS has_skill_sheet,
  count(*) FILTER (WHERE final_report_content IS NOT NULL) AS has_final_edit_quick,
  count(*) FILTER (WHERE EXISTS (
      SELECT 1 FROM report_feedback f WHERE f.report_id = in_scope.id AND f.final_output IS NOT NULL
  )) AS has_feedback_final,
  count(*) FILTER (WHERE EXISTS (
      SELECT 1 FROM report_feedback f WHERE f.report_id = in_scope.id AND f.lifecycle = 'copied'
  )) AS has_copy_event
FROM in_scope;


-- ===== Q4: Quick vs template — head to head =================================
WITH in_scope AS (
  SELECT r.id, r.final_report_content,
         CASE WHEN r.report_type='auto' THEN 'quick' ELSE 'template' END AS pipeline
  FROM reports r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN templates t ON t.id = r.template_id
  WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
    AND ( (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
       OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided') )
),
fb AS (SELECT DISTINCT report_id FROM report_feedback WHERE final_output IS NOT NULL)
SELECT s.pipeline,
       count(*) AS reports,
       count(*) FILTER (WHERE s.final_report_content IS NOT NULL) AS quick_final_edits,
       count(*) FILTER (WHERE fb.report_id IS NOT NULL) AS reports_with_feedback_final
FROM in_scope s
LEFT JOIN fb ON fb.report_id = s.id
GROUP BY s.pipeline
ORDER BY s.pipeline;


-- ===== Q5a: Skill-sheet quality — ephemeral analyser stats ==================
SELECT ess.analyser_model,
       count(*) AS sheets,
       round(avg(ess.analyser_latency_ms))::int AS avg_latency_ms,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ess.analyser_latency_ms)::int AS median_latency_ms
FROM ephemeral_skill_sheets ess
JOIN users u ON u.id = ess.user_id
WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
GROUP BY ess.analyser_model
ORDER BY sheets DESC;


-- ===== Q5b: Skill-sheet quality — scan-type clusters ========================
SELECT ess.scan_type_normalized, count(*) AS sheets
FROM ephemeral_skill_sheets ess
JOIN users u ON u.id = ess.user_id
WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
GROUP BY ess.scan_type_normalized
ORDER BY sheets DESC
LIMIT 25;


-- ===== Q6: Audit summary (reuses existing report_audits) ====================
WITH in_scope AS (
  SELECT r.id
  FROM reports r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN templates t ON t.id = r.template_id
  WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
    AND ( (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
       OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided') )
)
SELECT a.overall_status, count(*) AS audits
FROM report_audits a
JOIN in_scope s ON s.id = a.report_id
GROUP BY a.overall_status
ORDER BY audits DESC;


-- ===== Q6b: Audit — per-criterion status breakdown ==========================
WITH in_scope AS (
  SELECT r.id
  FROM reports r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN templates t ON t.id = r.template_id
  WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
    AND ( (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
       OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided') )
)
SELECT c.criterion, c.status, count(*) AS n
FROM report_audit_criteria c
JOIN report_audits a ON a.id = c.audit_id
JOIN in_scope s ON s.id = a.report_id
GROUP BY c.criterion, c.status
ORDER BY c.criterion, c.status;


-- ===== Q7: Template refinement (skill_sheet_guided templates) ===============
SELECT t.id, t.name,
       count(v.id) AS versions,
       t.usage_count,
       t.last_used_at
FROM templates t
JOIN users u ON u.id = t.user_id
LEFT JOIN template_versions v ON v.template_id = t.id
WHERE lower(u.email) NOT IN ('hassan.ahmad.ucl@gmail.com')
  AND t.template_config->>'generation_mode' = 'skill_sheet_guided'
GROUP BY t.id, t.name, t.usage_count, t.last_used_at
ORDER BY versions DESC;
