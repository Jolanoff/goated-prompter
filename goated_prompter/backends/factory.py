"""Backend selection kept separate from node and prompt logic."""

from .base import BackendConfigurationError


def canonical_backend_name(value):
    name = str(value or "").strip().lower().replace("-", "_")
    return {"debug": "mock", "openai": "openai_compatible",
            "llama_cpp": "local_llama_cpp", "llamacpp": "local_llama_cpp"}.get(name, name)


def create_backend(config):
    activity_callback = (config or {}).get("_activity_callback")
    backend_name = canonical_backend_name((config or {}).get("backend"))
    if not backend_name:
        raise BackendConfigurationError(
            "No Goated Prompter backend configured. Copy config.example.json to config.json and select a backend."
        )

    if backend_name == "mock":
        from .mock import MockBackend

        backend = MockBackend()
        backend.activity_callback = activity_callback
        return backend

    if backend_name == "openai_compatible":
        from .openai_compatible import OpenAICompatibleBackend

        settings = config.get("openai_compatible", {})
        if not isinstance(settings, dict):
            raise BackendConfigurationError("openai_compatible configuration must be an object.")
        backend = OpenAICompatibleBackend(settings)
        backend.activity_callback = activity_callback or backend.activity_callback
        backend.register_interrupt = config.get("_register_interrupt") or backend.register_interrupt
        backend.unregister_interrupt = config.get("_unregister_interrupt") or backend.unregister_interrupt
        return backend

    if backend_name == "local_llama_cpp":
        from .local_llama_cpp import LocalLlamaCppBackend

        settings = config.get("local_llama_cpp", {})
        backend = LocalLlamaCppBackend(settings)
        backend.activity_callback = activity_callback or backend.activity_callback
        backend.register_interrupt = config.get("_register_interrupt")
        backend.unregister_interrupt = config.get("_unregister_interrupt")
        return backend

    raise BackendConfigurationError(f"Unsupported Goated Prompter backend: {backend_name}")
