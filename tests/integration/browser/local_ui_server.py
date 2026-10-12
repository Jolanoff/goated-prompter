"""Real local API with a delayed mock service for browser integration tests only."""

from pathlib import Path
import os
import sys
import time
import json
import re
from unittest.mock import patch

from tests.support.artifacts import task_paths
from tests.support.safety import private_storage_guard, synthetic_storage

from aiohttp import web
from local_app import create_app
from goated_prompter.features.builder.service import GoatedPrompterService
from goated_prompter.backends.mock import MockBackend


class DatasetUIMock(MockBackend):
    """Schema-aware Dataset fixture; automatic planning cannot rely on fallback."""
    def generate(self, instruction):
        stage = instruction.diagnostic_stage
        if stage == "dataset:ideas:brainstorm":
            from tests.support.dataset import brainstorm_fixture
            result = json.dumps(brainstorm_fixture(json.loads(instruction.user_message)["requested_events"]))
        elif stage == "dataset:planning":
            from goated_prompter.options.dataset import BODIED_KINDS
            context = json.loads(instruction.user_message)
            rows = []
            for spec in context["assignments"]:
                participants = []
                for item in spec["participants"]:
                    bodily = item["kind"] in BODIED_KINDS
                    participants.append({"id": item["id"], "role": item["role"] or "subject",
                        "pose": item["pose"] or ("resting" if item["kind"] == "animal" else "standing" if bodily else ""),
                        "location": item["location"] or "center",
                        "support": item["support"] or ("four_paws_on_ground" if item["kind"] == "animal" else "feet_on_floor" if bodily else "")})
                rows.append({"index": spec["index"], "action": spec["action"], "setting": spec["setting"],
                    "participants": participants, "contacts": spec["contacts"], "supports": spec.get("supports", [])})
            result = json.dumps(rows)
        elif stage.startswith("dataset:validation:"):
            context = json.loads(instruction.user_message)
            if ":batch:" in stage:
                result = json.dumps([{"id": item["id"], "status": "pass", "evidence": [
                    {"index": context["descriptions"][0]["index"], "quote": context["descriptions"][0]["text"]}]}
                    for item in context["requirements"]])
            else:
                rows = []
                for item in context:
                    quote = item["evidence_quotes"][0]
                    description = item["description"].casefold()
                    def observed(subject):
                        labels = dict(subject["normalization_labels"])
                        if subject["kind"] not in {"object", "product", "environment", "style", "text", "concept", "other"}:
                            if not labels["pose"]:
                                labels["pose"] = ("seated" if re.search(r"\bsits?\b|\bseated\b", description) else
                                    "standing" if "feet_on_floor" in description or "feet on the floor" in description else "unknown")
                            if not labels["support"]:
                                labels["support"] = ("setting.bench" if "bench" in description and labels["pose"] == "seated" else
                                    "feet_on_floor" if "feet_on_floor" in description or "feet on the floor" in description else
                                    "four_paws_on_ground" if "four_paws_on_ground" in description else "unknown")
                        if not labels["location"]:
                            labels["location"] = next((value for value in ("center", "left", "right", "foreground", "background")
                                                       if value in description), "unknown")
                        labels["role"] = labels["role"] or "subject"
                        return {"id": subject["id"], **labels, "evidence": quote}
                    rows.append({"index": item["index"], "participants": [observed(subject) for subject in item["cast"]],
                        "contacts": [{**edge, "evidence": quote} for edge in item["contact_labels"]],
                        "setting": item["setting_to_identify"] or "unknown", "setting_evidence": quote,
                        "action": item["checks"][0]["text"], "action_evidence": quote,
                        "category": next((check["text"].split()[2] for check in item["checks"] if check["id"] == "category"), "general"),
                        "requirements": [{"id": check["id"], "status": "pass", "evidence": quote} for check in item["checks"]],
                        "conflicts": []})
                result = json.dumps(rows)
        elif stage == "dataset:ideas":
            from tests.helpers import dataset_idea_fixture
            context = json.loads(instruction.user_message)
            used = {" ".join(idea.casefold().split()) for idea in context["recently_used_ideas"]}
            used.update(" ".join(row["idea"].casefold().split()) for row in context["existing_ideas"])
            rows = []
            for row in context["assignments"]:
                idea = row["input"] or f"Mock activity{row['index']}"
                if not row["input"]:
                    while " ".join(idea.casefold().split()) in used:
                        idea += " revised"
                used.add(" ".join(idea.casefold().split()))
                spec = row["scene_spec"]
                mechanics = ". ".join(f"{item['name']} ({item['traits']}) is {item['pose'] or 'displayed'} "
                    f"at {item['location']}, with support {item['support'] or 'not applicable'}" for item in spec["participants"])
                contacts = ". ".join(f"{edge['source']} contacts {edge['target']}" for edge in spec["contacts"])
                support = ". ".join(f"{edge['source']} is supported by {edge['target']}" for edge in spec.get("supports", []))
                rows.append(dataset_idea_fixture(row["index"], idea=idea,
                    scene=f"mock scene {row['index']}: {idea}. {spec['action']}. {mechanics}. {contacts}. {support}. {spec['setting']}"))
            result = json.dumps(rows)
        elif stage == "builder:scene_planning":
            context = json.loads(instruction.user_message)
            return json.dumps({"primary_action": context["user_request"],
                               "staging": "Keep the requested subjects and relationships."})
        elif stage.startswith("dataset:understanding"):
            from tests.helpers import dataset_understanding_fixture
            source = json.loads(instruction.user_message)["source"]
            self.dataset_trigger = source.get("trigger", "")
            result = json.dumps(dataset_understanding_fixture(requested_generation=source["subject"],
                hard=[{"scope": "all_outputs", "text": rule} for rule in source["constraints"].splitlines() if rule.strip()],
                rules=[{"scope": "all_outputs", "text": rule} for rule in source["constraints"].splitlines() if rule.strip()],
                clarifications=["Breaking what?"] if "unclear breaking" in source["subject"] and "breaking a board" not in source["constraints"] else []))
        elif re.match(r"dataset:\d+", stage):
            if "The application inserts the locked trigger" in instruction.system_message:
                result = instruction.user_message
            else:
                marker = ("Include exact case-sensitive trigger wording: "
                          if "Include exact case-sensitive trigger wording: " in instruction.system_message
                          else "Required subjects/attributes: ")
                supplied = instruction.system_message.split(marker, 1)[1]
                terms, _ = json.JSONDecoder().raw_decode(supplied)
                result = f"{', '.join(terms)}: {instruction.user_message}"
        else:
            return super().generate(instruction)
        time.sleep(.02)  # Leaves a real disconnect window without using inference.
        self.emit_activity("request", model="dataset-ui-mock", messages=instruction.to_messages(), parameters={})
        self.emit_activity("response_delta", text=result)
        self.emit_activity("response_complete", finish_reason="stop")
        return result


def dataset_ui_backend(config):
    backend = DatasetUIMock()
    backend.activity_callback = config.get("_activity_callback")
    return backend


class DelayedMockService(GoatedPrompterService):
    def _generate(self, request, text_only=False):
        time.sleep(1)
        return super()._generate(request, text_only=text_only)


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    _, scratch = task_paths(os.environ.get("GOATED_TEST_TASK_KEY", "browser-tests"), "browser")
    with synthetic_storage(scratch) as data:
        port = int(os.environ.get("GOATED_UI_TEST_PORT", "8190"))
        with patch("goated_prompter.features.dataset.service.create_backend", side_effect=dataset_ui_backend), \
                patch("goated_prompter.features.dataset.understanding.create_backend", side_effect=dataset_ui_backend), \
                patch("goated_prompter.features.builder.service.create_backend", side_effect=dataset_ui_backend), \
                patch("local_app.get_process_manager"):
            # Exercise accepted aliases through the real API, not only factory tests.
            web.run_app(create_app(port=port, config_loader=lambda: {"backend": " DeBuG "}, settings_path=Path(data) / "settings.json",
                                   service_factory=DelayedMockService), host="127.0.0.1",
                        port=port)
