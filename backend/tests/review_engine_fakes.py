"""Shared fakes for review-engine tests: Jev answers by question-id prefix, a stub Qwen, input builders."""
from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.report_review import quick_section_names
from rapid_reports_ai.review_engine.items import ReviewInput

SEL_ABNORMAL = {"choice": "abnormal_finding", "probabilities": {
    "abnormal_finding": 0.9, "limitation": 0.0, "normal_or_negative": 0.1, "protocol_note": 0.0, "comparison": 0.0,
    "mixed_abnormal_and_normal": 0.0}}
STATED = {"choice": "stated", "probabilities": {"stated": 0.9, "partial": 0.05, "absent": 0.05}}


def jev(over=None, calls=None):
    """An async rc._jev stand-in. `over` maps a question id (or a prefix ending in '*') to an answer.
    Defaults: selector abnormal and reportable, every dictated line stated, every positive clause supported (W1n),
    every other noul question (contradiction, certainty, ...) low."""
    over = over or {}

    def answer(k):
        if k in over:
            return over[k]
        for pat, v in over.items():
            if pat.endswith("*") and k.startswith(pat[:-1]):
                return v
        if k.startswith("sel"):
            return SEL_ABNORMAL
        if k.startswith("lt") or k.startswith("sup"):
            return {"noul": 0.9}
        if k.startswith("i"):
            return STATED
        return {"noul": 0.1}

    async def fake(state, qs):
        if calls is not None:
            calls.append((state, dict(qs)))
        return {k: answer(k) for k in qs}
    return fake


def model(output, calls=None):
    """An async _run_agent_with_model stand-in returning `output` (or output(kwargs) if callable)."""
    class R:
        pass

    async def fake(**kw):
        if calls is not None:
            calls.append(kw)
        r = R()
        r.output = output(kw) if callable(output) else output
        return r
    return fake


def inp(report, dictation, options=None, quality_check=None, pathway="quick", synthesis=None, history="",
        scan="CT abdomen", title=None, pre_edit=None):
    art = GenerationArtifacts(report=report, dictated_findings=dictation, sections=quick_section_names(report),
                              options=options or [], brief=None, quality_check=quality_check)
    return ReviewInput(report_id="00000000-0000-0000-0000-000000000001", pathway=pathway, artifacts=art,
                       clinical_history=history, scan_type=scan, study_title=title, synthesis=synthesis,
                       pre_edit_report=pre_edit)
