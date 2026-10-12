"""Reusable Dataset drafts, accepted scenes and controlled backend responses."""

from contextlib import contextmanager
from dataclasses import replace
import json

from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.features.dataset.service import default_dataset_draft
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from goated_prompter.features.dataset.scene_spec import Participant, SceneSpec
from goated_prompter.features.dataset.validation import text_signature
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.batch_planner import plan_scene_specs
from goated_prompter.features.dataset.ideas import creative_directions, ideas_instruction
from goated_prompter.features.dataset.private_vocabulary import Vocabulary

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
    # Tests pin exact trigger wording unless they turn expansion on; the app's default is expansion.
    return {**default_dataset_draft(), "trigger": "ohwx_person", "expand_trigger": False,
            "subject": "A woman with short black hair and a red jacket.",
            "_confirmed_intent": dataset_understanding_fixture(), **changes}


def saved_scene(index=1, **changes):
    row = {**dataset_idea_fixture(index), "input": "", "scene": f"A boxer punches a training bag at station {index}.",
             "self_check": "PASS", "idea_status": "valid", "scene_status": "valid", "prompt_status": "not_generated", **changes}
    if "scene_spec" not in changes:
        spec = SceneSpec(index, "general", row["idea"], (Participant("P1", "the subject", "", "", "", ""),))
        row["scene_spec"] = spec.to_dict()
        row.setdefault("scene_validation", {"text_signature": text_signature(row["scene"]), "spec_signature": spec.signature,
            "observation": scene_observation(spec, row["scene"])})
    return row


def frozen_specs(data, *, salt=0, catalog=None):
    """Supply accepted plans to tests whose seam starts at Ideas, without calling a planner model."""
    provisional = plan_scene_specs(data, dataset_assignments(data),
        directions=creative_directions(data, range(1, data["amount"] + 1), salt, vocabulary={}),
        catalog=Vocabulary() if catalog is None else catalog)
    return {index: replace(spec, state="frozen") for index, spec in provisional.items()}


def frozen_ideas_instruction(data, assignments, **options):
    return ideas_instruction(data, assignments, scene_specs=frozen_specs(data), **options)


def planned_scene(data, index=1, *, catalog=None, **changes):
    return checked_scene(saved_scene(index, **changes), spec=frozen_specs(data, catalog=catalog)[index])


def vocabulary_record(label, category, *, sexes=("unspecified", "unspecified"), pose="seated", contacts=None):
    """A declared synthetic arrangement; labels carry no inferred mechanics."""
    owners = [chr(ord("A") + index) for index in range(len(sexes))]
    pairs = {"oral": ("mouth", "genitals"), "anal": ("genitals", "anus"),
             "vaginal": ("genitals", "vagina"), "feet": ("mouth", "feet")}
    if contacts is None:
        source, target = pairs.get(category, (None, None))
        contacts = [{"from": f"{owners[0]}.{source}", "to": f"{owners[-1]}.{target}"}] if source else []
    support = {"seated": "supported_by_chair", "standing": "feet_on_floor", "kneeling": "knees_on_floor"}[pose]
    return {"id": label, "label": label, "category": category, "participantCount": len(sexes),
        "participants": {owner: {"pose": pose, "location": ("left", "right", "center", "background")[index % 4], "sex": sex}
                         for index, (owner, sex) in enumerate(zip(owners, sexes))},
        "contacts": contacts, "physicalConstraints": dict.fromkeys(owners, support)}


def vocabulary_text(*entries):
    return "".join(f"[{section}]\n{json.dumps(record)}\n" for section, record in entries)


def specified_ideas(rows, data, *, salt=0):
    specs = frozen_specs(data, salt=salt)
    return [{**row, "scene_spec": specs[row["index"]].to_dict()} for row in rows]


def checked_scene(row, *, spec=None):
    spec = SceneSpec.from_dict(row["scene_spec"]) if spec is None else spec
    return {**row, "scene_spec": spec.to_dict(), "scene_validation": {
        "text_signature": text_signature(row["scene"]), "spec_signature": spec.signature,
        "observation": scene_observation(spec, row["scene"])}, "self_check": "PASS", "scene_status": "valid"}


def scene_observation(spec, scene):
    """Faithful external-checker fixture; negative cases supply their own conflicting observations."""
    return {"index": spec.index, "participants": [{"id": item.id,
        **{key: getattr(item, key) for key in ("role", "pose", "location", "support")}, "evidence": scene}
        for item in spec.participants], "contacts": [{"source": item.source, "target": item.target, "evidence": scene}
        for item in spec.contacts], "setting": spec.setting or "unknown", "setting_evidence": scene if spec.setting else "",
        "requirements": [{"id": key, "status": "pass", "evidence": scene} for key in (
            "action", *(f"subject:{item.id}" for item in spec.participants), *(f"hard:{index}" for index in range(len(spec.hard))),
            *(("concept",) if spec.concept else ()),
            *(("category",) if spec.route == "adult" and spec.category in {"oral", "anal", "vaginal", "feet"} else ()))],
        "action": spec.action, "action_evidence": scene, "category": spec.category, "conflicts": []}


def checked_writer_responses(session, outputs, scenes):
    """Script writer outputs separately from the new external fidelity-check responses."""
    outputs = iter(outputs)
    specs = {row["index"]: SceneSpec.from_dict(row["scene_spec"]) for row in scenes}
    def generate(instruction):
        if instruction.diagnostic_stage.startswith("dataset:validation:"):
            return json.dumps([scene_observation(specs[row["index"]], row["description"])
                              for row in json.loads(instruction.user_message)])
        output = next(outputs)
        if isinstance(output, Exception):
            raise output
        return output
    session.generate.side_effect = generate


class CheckedWriterBackend(GoatedPrompterBackend):
    name = "checked-writer"

    def __init__(self, outputs, scenes):
        self.outputs, self.calls = iter(outputs), []
        self.specs = {row["index"]: SceneSpec.from_dict(row["scene_spec"]) for row in scenes}

    @property
    def writes(self):
        return [call for call in self.calls if not call.diagnostic_stage.startswith("dataset:validation:")]

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage.startswith("dataset:validation:"):
            return json.dumps([scene_observation(self.specs[row["index"]], row["description"])
                              for row in json.loads(instruction.user_message)])
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output


class CaptureBackend(GoatedPrompterBackend):
    name = "dataset-capture"

    def __init__(self, scenes=()):
        self.calls, self.sessions = [], 0
        self.specs = {row["index"]: SceneSpec.from_dict(row["scene_spec"]) for row in scenes}
        self.scenes = {row["index"]: row["scene"] for row in scenes}

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        yield self

    def generate(self, instruction):
        self.calls.append(instruction)
        stage = instruction.diagnostic_stage
        if stage == "dataset:planning":
            context = json.loads(instruction.user_message)
            return json.dumps([{"index": row["index"], "action": row["action"], "setting": row["setting"],
                "participants": [{key: item[key] for key in ("id", "role", "pose", "location", "support")}
                                 for item in row["participants"]], "contacts": row["contacts"]}
                for row in context["assignments"]])
        if stage == "dataset:ideas":
            context = json.loads(instruction.user_message)
            self.specs.update((row["index"], SceneSpec.from_dict(row["scene_spec"])) for row in context["assignments"])
            self.scenes.update((row["index"], dataset_idea_fixture(row["index"])["scene"]) for row in context["assignments"])
            return json.dumps([dataset_idea_fixture(row["index"]) for row in context["assignments"]])
        if stage == "dataset:ideas:brainstorm":
            context = json.loads(instruction.user_message)
            return json.dumps([{**row, "index": spec["index"]} for row, spec in zip(
                brainstorm_fixture(len(context["scene_specs"])), context["scene_specs"])])
        if stage.startswith("dataset:validation:"):
            return json.dumps([scene_observation(self.specs[row["index"]], row["description"])
                              for row in json.loads(instruction.user_message)])
        return "ohwx_person " + self.scenes[int(stage.split(":")[1])]
