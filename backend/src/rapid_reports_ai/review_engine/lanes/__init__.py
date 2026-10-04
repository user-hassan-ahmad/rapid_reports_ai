"""Lanes (spec §6.1). Each lane turns the shared context into candidates; each is independently switchable."""
from __future__ import annotations

from typing import List, Optional, Protocol

from pydantic import BaseModel, ConfigDict

from ..alignment import Alignment, Pair
from ..items import Candidate, ReviewInput
from ..jev_pass import JevPass

# Alignment is a confidence-gated supporting tool (ledger L-56): a lane reads a pair only when it is confident.
PAIR_CONFIDENT = 0.5   # provisional: Gate F (shadow read of alignment-driven anchors)


def confident(p: Pair) -> bool:
    return p.how in ("exact", "number") or (p.how != "level_conflict" and p.score >= PAIR_CONFIDENT)


class LaneContext(BaseModel):
    """What every lane reads: the alignment, the shared Jev pass (None when no Jev lane runs) and the code checks.
    Spec §6.1's `candidates(inp, al)` gains the shared pass so the batched Jev requests are made once."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    alignment: Alignment
    jev: Optional[JevPass] = None
    checks: List[Candidate] = []


class Lane(Protocol):
    name: str

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]: ...


def registry() -> List[Lane]:
    """Every lane, in spec order (imported here, not at module top: the lane modules import this package)."""
    from .accuracy import AccuracyLane
    from .additions import AdditionsLane
    from .coverage import CoverageLane
    return [CoverageLane(), AccuracyLane(), AdditionsLane()]
