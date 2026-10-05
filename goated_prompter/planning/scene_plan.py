"""A semantic/staging plan, deliberately distinct from resolved image evidence."""

from dataclasses import dataclass
import json
from .constraints import COMPILED_CONTRACT


@dataclass(frozen=True)
class PromptScenePlan:
    details: dict
    compiled_request: object

    def supporting_input(self):
        return ("RESOLVED SCENE PLAN — SUPPORTING INTERPRETATION\n"
                "The original user intent remains authoritative. Explicit user requirements > "
                "preserved reference facts > this staging interpretation > optional Director embellishment. "
                "Resolve physical relationships only; never replace action, subjects, pose mechanics or literal text. "
                "Target, Director, Creativity and Length still govern expression and permitted enrichment.\n"
                + COMPILED_CONTRACT + "\n" + json.dumps(self.details, ensure_ascii=False))
