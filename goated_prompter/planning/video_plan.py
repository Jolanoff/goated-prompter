"""Temporal plan; H3 syntax, media roles and shot structure belong to the writer."""

from dataclasses import dataclass
import json
from .constraints import COMPILED_CONTRACT


@dataclass(frozen=True)
class VideoScenePlan:
    details: dict
    compiled_request: object

    def supporting_input(self):
        return ("VIDEO SCENE PLAN — SUPPORTING INTERPRETATION\n"
                "USER REQUEST remains authoritative. Existing reference analysis owns source roles; "
                "the supplied shot outline owns shot count/order/timing; exact dialogue remains verbatim. "
                "Media tokens remain symbolic and UNSEEN. Planned choreography is the requested action, "
                "not inspected source-video content. Never claim it was observed/extracted from media, "
                "upgrade reference roles, or import unrequested source appearance, environment or audio. "
                "Use only the supporting motion/interaction details. H3 syntax, timestamps, speaker IDs "
                "and output sections remain the existing writer's responsibility.\n"
                + COMPILED_CONTRACT + "\n" + json.dumps(self.details, ensure_ascii=False))
