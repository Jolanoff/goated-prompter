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


class BackendCapabilityError(GoatedPrompterError):
    """The selected backend cannot handle the supplied request modality."""


class ImageEncodingError(GoatedPrompterError):
    """A ComfyUI image could not be prepared safely for a vision backend."""


class GoatedPrompterBackend(ABC):
    """Minimal backend interface; heavy implementations may import lazily."""

    name = "unknown"
    supports_text = True
    supports_vision = False

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
