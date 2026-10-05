"""Common outer planning outcome, without imposing a universal scene schema."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanningResult:
    success: bool
    plan: Any = None
    warnings: tuple = ()
    fallback_allowed: bool = True
    status: str = "direct"
    error: str = None

    def __iter__(self):
        # Keep existing workflow callers' (plan, status) unpacking contract.
        yield self.plan
        yield self.status
