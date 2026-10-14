"""Rules shared by both stack briefs (integration spec §6, D22): kept once here so the quick and template paths can
never disagree."""
SELECTED_RECS = "Recommendations (selected by the radiologist):"

RECOMMENDATIONS_RULE = (
    "- **Recommendations:** no recommendation appears unless the confirmed conclusion contains one or the FINDINGS "
    f"input has a line starting '{SELECTED_RECS}'. A selected recommendation is written, in report style, as the "
    "impression's last line; never a separate section, never in the findings.")
