"""Dependency-free backend for assembly and UI smoke testing."""

from .base import GoatedPrompterBackend
from ..diagnostics import payload_without_binary_images


class MockBackend(GoatedPrompterBackend):
    name = "mock"

    def generate(self, instruction):
        messages = instruction.to_messages()
        safe = payload_without_binary_images({"messages": messages})
        self.emit_activity("request", model="mock", messages=safe["messages"], parameters={})
        idea = instruction.user_message.strip()
        result = f"[Mock Goated Prompter] {idea}"
        self.emit_activity("response_delta", text=result)
        self.emit_activity("response_complete", finish_reason="stop")
        return result
