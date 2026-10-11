"""Backend configuration fixtures and the shared output-format response script."""

from goated_prompter.backends.base import GoatedPrompterBackend

CONFIGURED_BACKENDS = (
    ("mock", "mock"), ("debug", "mock"), (" MOCK ", "mock"), (" Debug ", "mock"),
    ("openai", "openai_compatible"), ("openai_compatible", "openai_compatible"),
    ("OpenAI-Compatible", "openai_compatible"), (" OPENAI ", "openai_compatible"),
)


def backend_config(name):
    return {"backend": name, "openai_compatible": {"base_url": "http://127.0.0.1:1/v1", "model": "test"}}


class ScriptedBackend(GoatedPrompterBackend):
    name = "scripted"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def generate(self, instruction):
        self.calls.append(instruction)
        return next(self.outputs)
