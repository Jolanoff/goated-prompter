"""Dependency-free backend for assembly and UI smoke testing."""

from .base import GoatedPrompterBackend


class MockBackend(GoatedPrompterBackend):
    name = "mock"

    def generate(self, instruction):
        idea = instruction.user_message.strip()
        return f"[Mock Goated Prompter] {idea}"
