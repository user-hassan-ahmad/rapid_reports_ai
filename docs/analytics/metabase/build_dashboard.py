"""Build the Skill-Sheet Report Analytics dashboard in Metabase.

Idempotent: creates a new dashboard each run (Metabase has no upsert-by-name);
archive the previous one first via API or UI if rebuilding.

Cards all read from `v_skillsheet_reports` which now pins to rubric v2.1 (Sonnet
judge, fixed inputs). Update `00_view_v_skillsheet_reports.sql` first if the
underlying scoring changes.

Run:  python build_dashboard.py
Env:  METABASE_URL, METABASE_API_KEY (in backend/.env)
"""
import os, sys, json
from pathlib import Path
import urllib.request, urllib.error

# Load env
for line in Path(__file__).resolve().parents[3].joinpath("backend/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

BASE = os.environ["METABASE_URL"].rstrip("/")
KEY  = os.environ["METABASE_API_KEY"]
DB_ID = 2  # 'railway' Postgres in this Metabase instance
DASHBOARD_NAME = "Skill-Sheet Report Analytics (v2.1)"

def api(method: str, path: str, body=None):
    req = urllib.request.Request(f"{BASE}{path}", method=method,
        headers={"x-api-key": KEY, "Content-Type": "application/json"})
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} on {method} {path}: {e.read()[:500]}", file=sys.stderr)
        raise

def native_card(name: str, sql: str, display: str = "table", viz: dict | None = None) -> int:
    """Create a native-SQL card. Returns the card id."""
    body = {
        "name": name,
        "dataset_query": {"type": "native", "database": DB_ID,
                          "native": {"query": sql, "template-tags": {}}},
        "display": display,
        "visualization_settings": viz or {},
    }
    r = api("POST", "/api/card", body)
    return r["id"]

# ----- Card definitions ---------------------------------------------------
# Every card reads `v_skillsheet_reports`. Quality_core is averaged DF+NF+OA.
CARDS = [
    ("Total reports scored",
     "SELECT COUNT(*) FROM v_skillsheet_reports WHERE quality_core IS NOT NULL",
     "scalar", None),

    ("Mean quality (DF+NF+OA / 3)",
     "SELECT ROUND(AVG(quality_core)::numeric, 2) FROM v_skillsheet_reports",
     "scalar", None),

    ("% of reports at quality_core ≥ 4",
     "SELECT ROUND(100.0 * SUM((quality_core >= 4)::int) / COUNT(*), 1) || ' %' "
     "FROM v_skillsheet_reports WHERE quality_core IS NOT NULL",
     "scalar", None),

    ("Reports with any low score (≤ 2 on DF / NF / OA)",
     "SELECT SUM((dictation_fidelity <= 2 OR normal_fill_appropriateness <= 2 OR output_adherence <= 2)::int) "
     "FROM v_skillsheet_reports",
     "scalar", None),

    ("Quality by pipeline",
     """SELECT pipeline,
              COUNT(*) AS reports,
              ROUND(AVG(dictation_fidelity)::numeric, 2)              AS dictation_fidelity,
              ROUND(AVG(normal_fill_appropriateness)::numeric, 2)     AS normal_fill,
              ROUND(AVG(output_adherence)::numeric, 2)                AS output_adherence,
              ROUND(AVG(quality_core)::numeric, 2)                    AS quality_core
         FROM v_skillsheet_reports
        GROUP BY pipeline ORDER BY pipeline""",
     "table", None),

    ("Quality by template (weakest first, n ≥ 4)",
     """SELECT COALESCE(template_name, '(quick)') AS template,
              COUNT(*) AS reports,
              ROUND(AVG(dictation_fidelity)::numeric, 2)              AS dictation_fidelity,
              ROUND(AVG(normal_fill_appropriateness)::numeric, 2)     AS normal_fill,
              ROUND(AVG(output_adherence)::numeric, 2)                AS output_adherence,
              ROUND(AVG(quality_core)::numeric, 2)                    AS quality_core
         FROM v_skillsheet_reports
        GROUP BY template_name HAVING COUNT(*) >= 4
        ORDER BY quality_core ASC""",
     "table", None),

    ("Per-user volume & quality",
     """SELECT user_email, pipeline,
              COUNT(*) AS reports,
              ROUND(AVG(quality_core)::numeric, 2) AS quality_core,
              SUM(has_final_edit::int)  AS edited,
              SUM(was_copied::int)      AS copied
         FROM v_skillsheet_reports
        GROUP BY user_email, pipeline
       HAVING COUNT(*) >= 3
        ORDER BY reports DESC""",
     "table", None),

    ("Score distribution by dimension",
     """SELECT dim, score, COUNT(*) AS n
          FROM (
            SELECT 'DF' AS dim, dictation_fidelity AS score FROM v_skillsheet_reports
            UNION ALL
            SELECT 'NF', normal_fill_appropriateness FROM v_skillsheet_reports
            UNION ALL
            SELECT 'OA', output_adherence FROM v_skillsheet_reports
          ) x
         WHERE score IS NOT NULL
         GROUP BY dim, score
         ORDER BY dim, score""",
     "bar", {"graph.dimensions": ["score"], "graph.metrics": ["n"],
             "graph.series_dimension": "dim"}),

    ("Weekly quality trend",
     """SELECT week, pipeline,
              COUNT(*) AS reports,
              ROUND(AVG(quality_core)::numeric, 2) AS quality_core
         FROM v_skillsheet_reports
        WHERE quality_core IS NOT NULL
        GROUP BY week, pipeline ORDER BY week""",
     "line", {"graph.dimensions": ["week"], "graph.metrics": ["quality_core"],
              "graph.series_dimension": "pipeline"}),

    ("Lowest-quality reports (drill in)",
     """SELECT report_id, created_at::date AS date, pipeline,
              COALESCE(template_name, '(quick)') AS template,
              user_email,
              dictation_fidelity AS df, normal_fill_appropriateness AS nf, output_adherence AS oa,
              quality_core
         FROM v_skillsheet_reports
        WHERE quality_core IS NOT NULL
        ORDER BY quality_core ASC, dictation_fidelity ASC
        LIMIT 30""",
     "table", None),

    ("Acceptance signal: edit/copy vs quality",
     """SELECT has_final_edit, was_copied,
              COUNT(*) AS reports,
              ROUND(AVG(quality_core)::numeric, 2) AS quality_core
         FROM v_skillsheet_reports
        WHERE quality_core IS NOT NULL
        GROUP BY has_final_edit, was_copied
        ORDER BY has_final_edit, was_copied""",
     "table", None),

    ("Quality by analyser model (quick pipeline)",
     """SELECT COALESCE(analyser_model, '(unknown)') AS analyser_model,
              COUNT(*) AS reports,
              ROUND(AVG(dictation_fidelity)::numeric, 2)              AS df,
              ROUND(AVG(normal_fill_appropriateness)::numeric, 2)     AS nf,
              ROUND(AVG(output_adherence)::numeric, 2)                AS oa,
              ROUND(AVG(quality_core)::numeric, 2)                    AS quality_core
         FROM v_skillsheet_reports
        WHERE pipeline = 'quick'
        GROUP BY analyser_model
        ORDER BY reports DESC""",
     "table", None),

    ("Audit signal vs judge quality (judge is stronger discriminator)",
     """SELECT COALESCE(audit_status, '(none)') AS audit_status,
              COUNT(*) AS reports,
              ROUND(AVG(quality_core)::numeric, 2) AS quality_core,
              ROUND(AVG(dictation_fidelity)::numeric, 2) AS df,
              ROUND(AVG(output_adherence)::numeric, 2) AS oa
         FROM v_skillsheet_reports
        GROUP BY audit_status
        ORDER BY audit_status""",
     "table", None),

    ("Report detail (set Report ID)",
     """SELECT * FROM v_skillsheet_reports
        WHERE report_id::text = {{report_id}}""",
     "table", None),
]

# ----- Layout: 18-col grid, simple stacking ------------------------------
# Top row: 4 scalars (4 cols each)
# Then: stacked tables / charts at width=18, varying height
def grid():
    out = []
    # row 1 — scalars
    for i, _ in enumerate(CARDS[:4]):
        out.append({"row": 0, "col": i*4, "size_x": 4, "size_y": 3})
    # remaining cards stacked full-width
    row = 3
    for i in range(4, len(CARDS)):
        out.append({"row": row, "col": 0, "size_x": 18, "size_y": 6})
        row += 6
    return out

def main():
    print(f"BASE={BASE}  DB={DB_ID}")
    # Build cards
    card_ids = []
    for name, sql, display, viz in CARDS:
        # Report detail needs a template tag for {{report_id}}
        body = {
            "name": name,
            "dataset_query": {"type": "native", "database": DB_ID,
                              "native": {"query": sql, "template-tags": {}}},
            "display": display,
            "visualization_settings": viz or {},
        }
        if "{{report_id}}" in sql:
            body["dataset_query"]["native"]["template-tags"] = {
                "report_id": {"id": "report_id", "name": "report_id",
                              "display-name": "Report ID", "type": "text", "required": False}
            }
            body["parameters"] = [{"id": "report_id", "name": "Report ID",
                                   "slug": "report_id", "type": "category", "target": ["variable", ["template-tag", "report_id"]]}]
        r = api("POST", "/api/card", body)
        card_ids.append(r["id"])
        print(f"  card {r['id']:>4} | {display:8} | {name}")

    # Create dashboard
    dash = api("POST", "/api/dashboard", {"name": DASHBOARD_NAME,
                                          "description": "v2.1 rubric (Sonnet judge, fixed inputs). Source: v_skillsheet_reports."})
    dash_id = dash["id"]
    print(f"dashboard {dash_id} created")

    # Place cards
    layout = grid()
    dashcards = [{"id": -(i+1), "card_id": cid, **layout[i]} for i, cid in enumerate(card_ids)]
    api("PUT", f"/api/dashboard/{dash_id}", {"dashcards": dashcards})
    print(f"dashboard {dash_id} populated: {BASE}/dashboard/{dash_id}")

if __name__ == "__main__":
    main()
