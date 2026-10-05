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
