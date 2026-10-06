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


def dataset_intent_fixture(**changes):
    return {"goal": "Preserve the supplied Dataset concept.", "character_count": None,
            "identity_policy": "fixed", "fixed_identity_facts": [], "required_rules": [],
            "allowed_variation": [], "action_options": [], "blocking_questions": [], **changes}


def confirmed_dataset_payload(state, data, **options):
    """Seed only the approval boundary in tests focused on downstream behavior."""
    from goated_prompter.dataset import validate_dataset_draft
    ticket = state.dataset_intents.register(validate_dataset_draft(data), dataset_intent_fixture())
    return {"input": data, "confirmation_token": ticket["confirmation_token"], **options}
