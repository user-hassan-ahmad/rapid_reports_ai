"""Qwen reasoning-off with probabilities: the calibration contrast for Jev (D-03).

The shipped Qwen-off candidates (Groq qwen/qwen3.6-27b) return hard labels, and Groq
rejects `logprobs` for that model. Cerebras qwen-3.8-27b with reasoning_effort none
returns top-logprobs, so here each Jev question is asked of Qwen on its own and the
answer's probability is read from the first generated token:
  choice  options numbered 1..k (each "N. name: description"), reply the number;
          p(option) = renormalised mass on its digit among the top logprobs
  noul    the statement (+ its true/false criteria when it has them), reply yes/no;
          p(true) = mass(yes) / (mass(yes) + mass(no))
The user message is the same JSON state Jev receives; instructions and criteria are
the questions' own texts, passed in, never copied. Answers come back Jev-shaped.

Eval only (bake-offs). Different model version and provider from the shipped
candidate; every report says so.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from math import exp
from typing import Any

import httpx

QWEN_LP_MODEL = "qwen-3.8-27b"
QWEN_LP_URL = "https://api.cerebras.ai/v1/chat/completions"
QWEN_LP_LABEL = f"qwen-lp (Cerebras {QWEN_LP_MODEL}, reasoning off, first-token logprobs)"
TOP_LOGPROBS = 10
RETRIES = 4


class QwenLogprobError(RuntimeError):
    pass


def _user(state: dict[str, Any]) -> dict[str, str]:
    return {"role": "user", "content": json.dumps(state, indent=1, ensure_ascii=False)}


def choice_messages(state: dict[str, Any], question: dict[str, Any]) -> list[dict[str, str]]:
    lines = [
        "You answer one question about the JSON state of a radiologist's live dictation.",
        f"Question: {question['instructions']}",
        "Options:",
    ]
    lines += [f"{i}. {name}: {desc}" for i, (name, desc) in enumerate(question["criteria"].items(), start=1)]
    lines.append("Reply with the option number only.")
    return [{"role": "system", "content": "\n".join(lines)}, _user(state)]


def noul_messages(state: dict[str, Any], question: dict[str, Any]) -> list[dict[str, str]]:
    lines = [
        "You judge one statement about the JSON state of a radiologist's live dictation.",
        f"Statement: {question['instructions']}",
    ]
    crit = question.get("criteria")
    if crit:
        lines += [f"True when: {crit['true']}", f"False when: {crit['false']}"]
    lines.append("Reply yes if the statement is true of the state, no if it is false. One word.")
    return [{"role": "system", "content": "\n".join(lines)}, _user(state)]


def _mass(top: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in top:
        key = t["token"].strip().lower()
        out[key] = out.get(key, 0.0) + exp(t["logprob"])
    return out


def choice_probs(top: list[dict[str, Any]], options: list[str]) -> dict[str, float]:
    mass = _mass(top)
    raw = {name: mass.get(str(i), 0.0) for i, name in enumerate(options, start=1)}
    total = sum(raw.values())
    if total <= 0:
        raise QwenLogprobError(f"no option digit among top tokens: {[t['token'] for t in top]}")
    return {k: v / total for k, v in raw.items()}


def noul_prob(top: list[dict[str, Any]]) -> float:
    mass = _mass(top)
    yes, no = mass.get("yes", 0.0), mass.get("no", 0.0)
    if yes + no <= 0:
        raise QwenLogprobError(f"no yes/no among top tokens: {[t['token'] for t in top]}")
    return yes / (yes + no)


class QwenLogprob:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 20.0) -> None:
        self._api_key = api_key or os.environ.get("CEREBRAS_API_KEY") or ""
        if not self._api_key:
            raise QwenLogprobError("CEREBRAS_API_KEY is not set")
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_s)

    async def _top(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        body = {
            "model": QWEN_LP_MODEL, "messages": messages, "temperature": 0, "max_completion_tokens": 3,
            "reasoning_effort": "none", "logprobs": True, "top_logprobs": TOP_LOGPROBS,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(RETRIES):
            resp = await self._client.post(QWEN_LP_URL, json=body, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise QwenLogprobError(f"http {resp.status_code}: {resp.text[:200]}")
            content = ((resp.json()["choices"][0].get("logprobs") or {}).get("content")) or []
            if not content:
                raise QwenLogprobError("no logprobs in response")
            return content[0].get("top_logprobs") or []
        raise QwenLogprobError(f"http {resp.status_code} after {RETRIES} attempts")

    async def _one(self, state: dict[str, Any], q: dict[str, Any]) -> dict[str, Any]:
        if q["type"] == "choice":
            options = list(q["criteria"])
            probs = choice_probs(await self._top(choice_messages(state, q)), options)
            best = max(options, key=lambda o: probs[o])
            return {"type": "choice", "choice": best, "confidence": probs[best], "probabilities": probs}
        if q["type"] == "noul":
            return {"type": "noul", "noul": noul_prob(await self._top(noul_messages(state, q)))}
        raise QwenLogprobError(f"unsupported question type {q['type']!r}")

    async def answer(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Every question as its own call, in parallel; Jev-shaped answers plus latency_ms
        (wall time of the parallel batch)."""
        t0 = time.perf_counter()
        ids = list(questions)
        results = await asyncio.gather(*(self._one(state, questions[i]) for i in ids))
        out: dict[str, Any] = dict(zip(ids, results))
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
