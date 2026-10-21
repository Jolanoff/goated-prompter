"""Controlled vision engine for deterministic Caption tests."""

from contextlib import contextmanager


class VisionEngine:
    supports_vision = True

    def __init__(self):
        self.calls = []
        self.on_generate = None

    @contextmanager
    def generation_session(self):
        yield self

    def validate_instruction(self, instruction):
        assert instruction.image is not None

    def generate(self, instruction):
        self.calls.append(instruction)
        if self.on_generate:
            self.on_generate()
        return 'Caption: "A person lifts a box beside a table."'
