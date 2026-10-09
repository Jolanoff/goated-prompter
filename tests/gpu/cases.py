"""Seeded random cases composed from per-workflow fixture pools.

The seed fixes the generated inputs, not model sampling: the production backend
has no seed option, so identical GPU output is not guaranteed.
"""

import hashlib
import json
from pathlib import Path
import random

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_path(workflow):
    return FIXTURES / f"{workflow}.json"


def fixture_digest(workflow):
    return hashlib.sha256(fixture_path(workflow).read_bytes()).hexdigest()


def random_cases(workflow, seed, count):
    if type(seed) is not int:
        raise ValueError("Random cases require an explicit integer --seed.")
    if type(count) is not int or count < 1:
        raise ValueError("Random case count must be positive.")
    path = fixture_path(workflow)
    if not path.is_file():
        raise ValueError(f"No random-case fixture for workflow {workflow}.")
    pools = json.loads(path.read_text(encoding="utf-8"))["random_pools"]
    # A string seed is hashed deterministically, independent of PYTHONHASHSEED.
    rng = random.Random(f"{workflow}:{seed}")
    cases = []
    for index in range(1, count + 1):
        subject = rng.choice(pools["subjects"])
        action, setting = rng.choice(pools["actions"][subject["kind"]]), rng.choice(pools["settings"])
        constraint = rng.choice(pools["constraints"])
        request = f"{subject['text']} {action} {setting}."
        anchors = {"scene": [subject["text"].lower(), setting], "action": [action], "pose": [],
                   "constraint": [constraint] if constraint else []}
        if workflow == "minimax":
            camera, line = rng.choice(pools["cameras"]), rng.choice(pools["dialogue"])
            request += f" The camera {camera}."
            anchors["constraint"].append("camera " + camera)
            if line:
                request += " " + line
                anchors["constraint"].append("exact dialogue")
        if constraint:
            request += " " + constraint
        cases.append({"id": f"random-{workflow}-{seed}-{index}", "workflows": [workflow],
                      "dataset_type": subject["dataset_type"], "request": request, "anchors": anchors,
                      "random": {"seed": seed, "index": index}})
    return cases
