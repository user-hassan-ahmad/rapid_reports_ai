"""Checks against the real (private) bundle. Skipped in CI and whenever RR_PROTOCOL_LIBRARY_PATH is unset."""
import os

import pytest

from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB
from rapid_reports_ai.hybrid_stack.protocol_library import compose as C
from rapid_reports_ai.hybrid_stack.protocol_library import match as M
from rapid_reports_ai.quick_report_brief import stack_fallback

pytestmark = pytest.mark.skipif(not os.environ.get("RR_PROTOCOL_LIBRARY_PATH"), reason="private bundle not available")
SEX_ONLY = {"Pelvic organs"}


@pytest.fixture(scope="module")
def b():
    PB.reset_cache()
    bundle = PB.get_bundle()
    assert bundle is not None, "bundle failed to load; see the log"
    return bundle


def test_every_pick_resolves_and_composes(b):
    bad = []
    for e in b.entries:
        lat = "left" if e.laterality == "required" else None
        for ph in e.phase_sets():
            res = C.resolve(b, e.id, ph, lat)
            s = C.compose_sheet(b, res)
            missing = [r.name for r in res.regions if not r.quiet and r.name != "Other findings"
                       and r.name not in s.region_normals and r.name not in SEX_ONLY]
            if missing and len(missing) > len(res.regions) // 2:
                bad.append((e.id, ph, missing[:4]))
            assert stack_fallback(s.markdown, "", []) is not None
    assert not bad, bad[:10]


def test_display_names_find_themselves(b):
    misses = [e.id for e in b.entries if e.id not in [o.id for _, o in M.local_search(b, e.display_name, 3)]]
    assert len(misses) <= len(b.entries) // 50, misses[:10]
