"""The one server switch (integration spec §9.1, D5): the scratchpad stack, on unless RR_STACK=0. No imports from the
stack, so dictation_v2 and hybrid_stack both read it without a cycle."""
from __future__ import annotations

import os
from typing import Mapping


def stack_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_STACK", "1") != "0"
