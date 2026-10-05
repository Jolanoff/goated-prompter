"""Backend contracts and backend-specific errors."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from ..reference_map import reference_images


class GoatedPrompterError(RuntimeError):
    """Base error suitable for presentation to a Goated Prompter user."""


class BackendConfigurationError(GoatedPrompterError):
    """The selected backend is absent or invalid."""


class BackendGenerationError(GoatedPrompterError):
    """The selected backend failed while generating text."""

    def __init__(self, message, *, completion_state="provider_error", partial_text="", finish_reason=None):
        super().__init__(message)
        self.completion_state = completion_state
        self.partial_text = partial_text
        self.finish_reason = finish_reason


class BackendRunawayError(BackendGenerationError):
    """A bounded workflow exceeded its limit or entered a repetition loop."""

    def __init__(self, message, *, recoverable_text="", completion_state="provider_error", partial_text="", finish_reason=None):
        super().__init__(message, completion_state=completion_state, partial_text=partial_text, finish_reason=finish_reason)
        self.recoverable_text = recoverable_text


class BackendCapabilityError(GoatedPrompterError):
    """The selected backend cannot handle the supplied request modality."""


class ImageEncodingError(GoatedPrompterError):
    """A ComfyUI image could not be prepared safely for a vision backend."""


class GoatedPrompterBackend(ABC):
    """Minimal backend interface; heavy implementations may import lazily."""

    name = "unknown"
    supports_text = True
    supports_vision = False
    activity_callback = None

    def emit_activity(self, event_type, **details):
        """Publish user-visible request activity without coupling backends to the UI."""
        callback = getattr(self, "activity_callback", None)
        if callback is not None:
            try:
                callback({"type": event_type, **details})
            except Exception:
                # Observability must never break generation.
                pass

    def validate_vision_input(self, image):
        if image is not None and not self.supports_vision:
            raise BackendCapabilityError(
                f"Goated Prompter backend '{self.name}' does not support vision; disconnect IMAGE or select a vision-capable backend."
            )

    def validate_instruction(self, instruction):
        for image in reference_images(instruction).values():
            self.validate_vision_input(image)

    @contextmanager
    def generation_session(self):
        """Yield a backend usable for a related sequence of generation calls."""
        yield self

    @abstractmethod
    def generate(self, instruction):
        """Return one generated prompt for an assembled PromptInstruction."""
        raise NotImplementedError
