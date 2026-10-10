import httpx

from rapid_reports_ai.hybrid_stack.http import post_json


async def test_post_json_uses_the_given_transport():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["Authorization"]
        return httpx.Response(200, json={"ok": True})

    r = await post_json("https://x.test/v1", "k", {"a": 1}, 5.0, transport=httpx.MockTransport(handler))
    assert r.json() == {"ok": True} and seen["auth"] == "Bearer k"
