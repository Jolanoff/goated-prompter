"""Reusable Dataset drafts, accepted scenes and controlled backend responses."""

from contextlib import contextmanager
import json

from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.features.dataset.service import default_dataset_draft
from tests.helpers import dataset_idea_fixture

REPAIR = "REPAIR:\nThe user requires both an extreme close-up of only his eyes and clearly visible shoes; the eyes-only crop excludes the shoes.\nShould the image show only eyes, or widen the crop to include the shoes?"
SCENE = "A boxer extends one glove into a training bag, with planted feet and the opposite glove readable in a full-body three-quarter arena view."


BRAINSTORM_ACTIONS = ("vaults a fence", "juggles oranges", "chases a kite", "repairs a bicycle", "paints a mural",
    "feeds pigeons", "climbs a rope", "rows a boat", "flips pancakes", "plants a tree", "skips stones",
    "tunes a guitar", "builds a sandcastle", "walks a tightrope", "carries a ladder", "rescues a cat")


def brainstorm_fixture(count):
    """Distinct candidate events with typicality, as the brainstorm stage returns them."""
    return [{"event": f"The subject {BRAINSTORM_ACTIONS[index % len(BRAINSTORM_ACTIONS)]} at stop {index}.",
             "typicality": round(.1 + .8 * (index % 5) / 4, 2)} for index in range(count)]


def valid_draft(**changes):
    return {**default_dataset_draft(), "trigger": "ohwx_person",
            "subject": "A woman with short black hair and a red jacket.", **changes}


def saved_scene(index=1, **changes):
    return {**dataset_idea_fixture(index), "input": "", "scene": f"A boxer punches a training bag at station {index}.",
            "self_check": "PASS", "idea_status": "valid", "scene_status": "valid", "prompt_status": "not_generated", **changes}


class CaptureBackend(GoatedPrompterBackend):
    name = "dataset-capture"

    def __init__(self):
        self.calls, self.sessions = [], 0

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        yield self

    def generate(self, instruction):
        self.calls.append(instruction)
        stage = instruction.diagnostic_stage
        if stage == "dataset:ideas":
            context = json.loads(instruction.user_message)
            return json.dumps([dataset_idea_fixture(row["index"]) for row in context["assignments"]])
        if stage == "dataset:ideas:brainstorm":
            return json.dumps(brainstorm_fixture(json.loads(instruction.user_message)["requested_events"]))
        return "A distinct visual setup featuring ohwx_person in the requested concept."
