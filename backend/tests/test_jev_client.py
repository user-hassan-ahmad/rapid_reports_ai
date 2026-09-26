from __future__ import annotations

import asyncio

import httpx
import pytest

from rapid_reports_ai import jev_client

OK = {"answers": {"warm": {"type": "noul", "noul": 0.1}}, "usage": {}}


@pytest.fixture
def built(monkeypatch):
    """Patch the client builder: every client gets a MockTransport; count constructions."""
    made: list[httpx.AsyncClient] = []
    state = {"handler": lambda req: httpx.Response(200, json=OK)}

    def build(transport=None):
        c = httpx.AsyncClient(transport=transport or httpx.MockTransport(lambda r: state["handler"](r)))
        made.append(c)
        return c

    monkeypatch.setattr(jev_client, "_build_client", build)
    monkeypatch.setattr(jev_client, "_SHARED", None)
    monkeypatch.delenv("RR_JEV_FRESH_CLIENT", raising=False)
    return made, state


async def test_shared_client_is_reused_within_a_loop(built):
    made, _ = built
    assert jev_client.shared_client() is jev_client.shared_client()
    assert len(made) == 1


def test_new_loop_gets_new_client(built):
    made, _ = built

    async def get():
        return jev_client.shared_client()

    a = asyncio.run(get())
    b = asyncio.run(get())
    assert a is not b and len(made) == 2


async def test_post_without_transport_uses_one_client(built):
    made, _ = built
    for _ in range(2):
        r = await jev_client.jev_post({"x": 1}, "k", 3.0)
        assert r.status_code == 200
    assert len(made) == 1


async def test_post_sends_auth_and_body(built):
    _, state = built
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["url"] = str(req.url)
        seen["body"] = req.content
        return httpx.Response(200, json=OK)

    state["handler"] = handler
    await jev_client.jev_post({"a": 1}, "secret", 3.0)
    assert seen["auth"] == "Bearer secret" and seen["url"] == jev_client.JEV_URL and seen["body"] == b'{"a":1}'


async def test_post_with_transport_uses_that_transport(built):
    made, _ = built
    hit = []
    t = httpx.MockTransport(lambda req: hit.append(1) or httpx.Response(200, json=OK))
    await jev_client.jev_post({}, "k", 3.0, transport=t)
    assert hit == [1] and jev_client._SHARED is None  # never touched the shared client


async def test_fresh_flag_builds_per_call(built, monkeypatch):
    made, _ = built
    monkeypatch.setenv("RR_JEV_FRESH_CLIENT", "1")
    await jev_client.jev_post({}, "k", 3.0)
    await jev_client.jev_post({}, "k", 3.0)
    assert len(made) == 2 and all(c.is_closed for c in made)


async def test_warm_up_reports_ms_and_never_raises(built):
    _, state = built
    ms = await jev_client.warm_up("k")
    assert isinstance(ms, int) and ms >= 0
    state["handler"] = lambda req: httpx.Response(500, text="no")
    assert await jev_client.warm_up("k") is None

    def boom(req):
        raise httpx.ConnectError("down")

    state["handler"] = boom
    assert await jev_client.warm_up("k") is None
    assert await jev_client.warm_up("") is None  # no key: no call


@pytest.mark.parametrize("env,expected", [
    ({}, False),
    ({"RR_TRIAGE_DEBUG": "1"}, True),
    ({"RR_TRIAGE_SHADOW": "1"}, True),
    ({"RR_COVERAGE_CANDIDATE": "jev"}, True),
    ({"RR_COVERAGE_CANDIDATE": "qwen"}, False),
    ({"RR_TRIAGE_DEBUG": "0"}, False),
])
def test_warmup_wanted(monkeypatch, env, expected):
    for k in ("RR_TRIAGE_DEBUG", "RR_TRIAGE_SHADOW", "RR_COVERAGE_CANDIDATE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert jev_client.warmup_wanted() is expected


def test_warmup_not_wanted_without_key(monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert jev_client.warmup_wanted() is False


async def test_schedule_warm_up(built, monkeypatch):
    for k in ("RR_TRIAGE_DEBUG", "RR_TRIAGE_SHADOW", "RR_COVERAGE_CANDIDATE"):
        monkeypatch.delenv(k, raising=False)
    assert jev_client.schedule_warm_up() is None
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    task = jev_client.schedule_warm_up()
    assert task is not None and isinstance(await task, int)


async def test_aclose(built):
    c = jev_client.shared_client()
    await jev_client.aclose()
    assert c.is_closed and jev_client._SHARED is None
    await jev_client.aclose()  # idempotent


def _all_answers():
    choice = lambda c, opts: {"choice": c, "confidence": 0.9, "probabilities": {o: (0.9 if o == c else 0.02) for o in opts}}
    from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS
    from rapid_reports_ai.utterance_boundary import BOUNDARIES, PLACEMENTS
    noul = {"noul": 0.2}
    return {"answers": {
        "action": choice("append_new_finding", TRIAGE_ACTIONS), "is_correction": noul, "needs_committed_edit": noul,
        "standalone": noul, "section_0": noul, "LUNGS": noul, "asr_risk": noul,
        "boundary": choice("complete", BOUNDARIES), "placement": choice("new_line", PLACEMENTS),
    }, "usage": {}}


async def test_all_four_callers_share_one_client(built):
    from rapid_reports_ai.dictation_triage import JevTriager, TriageState
    from rapid_reports_ai.section_coverage import JevCoverage
    from rapid_reports_ai.utterance_boundary import JevBoundary
    from rapid_reports_ai.utterance_bundle import BundleState, JevBundle

    made, state = built
    state["handler"] = lambda req: httpx.Response(200, json=_all_answers())
    calls = [
        lambda: JevTriager(api_key="k").classify(TriageState("", "", "a nodule", "CT chest")),
        lambda: JevBundle(api_key="k").classify(BundleState("CT chest", "", "", "", "a nodule", ["LUNGS"])),
        lambda: JevCoverage(api_key="k").classify("lungs clear", ["LUNGS"], "CT chest"),
        lambda: JevBoundary(api_key="k").classify("CT chest", "", "a nodule", ""),
    ]
    for call in calls:
        await call()
        await call()
    assert len(made) == 1
