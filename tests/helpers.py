"""Test lifecycle helpers compatible with the project's Python 3.10 minimum."""

from contextlib import ExitStack


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
    from goated_prompter.dataset import validate_dataset_draft
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
    return {"index": index, "idea": f"A boxer practising a straight punch at station {index}.",
            "placement": "Boxer centered, facing the training bag.",
            "visibility": "The punching glove overlaps the bag; the opposite glove remains readable.",
            "camera": "Three-quarter front-side angle.", "framing": "Full body.",
            "context": "Arena training area.", **changes}
