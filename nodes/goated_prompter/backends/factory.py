"""Backend selection kept separate from node and prompt logic."""

from .base import BackendConfigurationError


def create_backend(config):
    backend_name = str((config or {}).get("backend") or "").strip().lower().replace("-", "_")
    if not backend_name:
        raise BackendConfigurationError(
            "No Goated Prompter backend configured. Copy config.example.json to config.json and select a backend."
        )

    if backend_name in {"mock", "debug"}:
        from .mock import MockBackend

        return MockBackend()

    if backend_name in {"openai", "openai_compatible"}:
        from .openai_compatible import OpenAICompatibleBackend

        settings = config.get("openai_compatible", {})
        if not isinstance(settings, dict):
            raise BackendConfigurationError("openai_compatible configuration must be an object.")
        return OpenAICompatibleBackend(settings)

    if backend_name in {"local_llama_cpp", "llama_cpp", "llamacpp"}:
        from .local_llama_cpp import LocalLlamaCppBackend

        settings = config.get("local_llama_cpp", {})
        return LocalLlamaCppBackend(settings)

    raise BackendConfigurationError(f"Unsupported Goated Prompter backend: {backend_name}")
