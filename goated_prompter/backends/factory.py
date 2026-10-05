"""Backend selection kept separate from node and prompt logic."""

from .base import BackendConfigurationError


def create_backend(config):
    activity_callback = (config or {}).get("_activity_callback")
    backend_name = str((config or {}).get("backend") or "").strip().lower().replace("-", "_")
    if not backend_name:
        raise BackendConfigurationError(
            "No Goated Prompter backend configured. Copy config.example.json to config.json and select a backend."
        )

    if backend_name in {"mock", "debug"}:
        from .mock import MockBackend

        backend = MockBackend()
        backend.activity_callback = activity_callback
        return backend

    if backend_name in {"openai", "openai_compatible"}:
        from .openai_compatible import OpenAICompatibleBackend

        settings = config.get("openai_compatible", {})
        if not isinstance(settings, dict):
            raise BackendConfigurationError("openai_compatible configuration must be an object.")
        backend = OpenAICompatibleBackend(settings)
        backend.activity_callback = activity_callback or backend.activity_callback
        backend.register_interrupt = config.get("_register_interrupt") or backend.register_interrupt
        backend.unregister_interrupt = config.get("_unregister_interrupt") or backend.unregister_interrupt
        return backend

    if backend_name in {"local_llama_cpp", "llama_cpp", "llamacpp"}:
        from .local_llama_cpp import LocalLlamaCppBackend

        settings = config.get("local_llama_cpp", {})
        backend = LocalLlamaCppBackend(settings)
        backend.activity_callback = activity_callback or backend.activity_callback
        backend.register_interrupt = config.get("_register_interrupt")
        backend.unregister_interrupt = config.get("_unregister_interrupt")
        return backend

    raise BackendConfigurationError(f"Unsupported Goated Prompter backend: {backend_name}")
