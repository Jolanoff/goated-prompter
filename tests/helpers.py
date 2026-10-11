"""Test lifecycle helpers compatible with the project's Python 3.10 minimum."""

from contextlib import ExitStack
import os
from pathlib import Path

from goated_prompter.features.dataset.private_vocabulary import VOCABULARY_FILE_ENV

# Tests never read the user's private vocabulary file; they use neutral placeholders instead.
PRIVATE_VOCABULARY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "private_vocabulary.txt"
os.environ[VOCABULARY_FILE_ENV] = str(PRIVATE_VOCABULARY_FIXTURE)


def enter_context(test_case, context):
    """Enter a context and release it with unittest's LIFO cleanup lifecycle.

    TestCase.enterContext is only available starting with Python 3.11.
    ExitStack provides the same context protocol and cleanup behavior on 3.10,
    including cleanup after a failed setUp or an asynchronous endpoint test.
    """
    stack = ExitStack()
    result = stack.enter_context(context)
    test_case.addCleanup(stack.close)
    return result


def confirmed_dataset_payload(state, data, **options):
    """Seed only the approval boundary in tests focused on downstream behavior."""
    from goated_prompter.features.dataset.service import validate_dataset_draft
    ticket = state.dataset_intents.register(validate_dataset_draft(data), dataset_understanding_fixture())
    return {"input": data, "confirmation_token": ticket["confirmation_token"], **options}


def dataset_understanding_fixture(**changes):
    return {"requested_generation": "A person practising boxing.",
            "character_count": None, "identity_policy": "random_per_prompt", "action_options": [],
            "hard": [], "soft": [], "free": [],
            "fixed": [], "may_vary": [], "must_vary": [], "rules": [],
            "visible_evidence": [], "interactions": [], "natural_occlusions": [],
            "visibility_to_preserve": [], "physical_conflicts": [],
            "expansion_freedom": "Expand only unspecified details.",
            "dataset_contents": "One training-image prompt in the selected format.",
             "clarifications": [], **changes}


def dataset_idea_fixture(index=1, **changes):
    return {"index": index, "idea": f"Boxer {index} practises at a station.",
            "scene": (f"At training station {index}, a boxer drives a straight punch into a swinging heavy bag; "
                      "the punching glove sinks into the leather while the other glove guards the chin. "
                      "Full-body three-quarter view in a dim arena training area lit by one overhead lamp."),
            **changes}
