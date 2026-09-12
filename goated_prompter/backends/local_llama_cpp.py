"""Optional local multimodal backend powered by an owned llama.cpp server."""

from contextlib import contextmanager
from dataclasses import replace

from .base import GoatedPrompterBackend
from .llama_cpp_process import LlamaCppLaunchConfig, get_process_manager
from .openai_compatible import OpenAICompatibleBackend


class LocalLlamaCppBackend(GoatedPrompterBackend):
    name = "local_llama_cpp"
    supports_vision = True

    def __init__(self, settings, process_manager=None):
        self.config = LlamaCppLaunchConfig.from_mapping(settings)
        self.context_reserve_tokens = settings.get("context_reserve_tokens", 1024)
        self.process_manager = process_manager or get_process_manager()

    def _client(self, runtime_config=None, runtime_diagnostics=None):
        active_config = runtime_config or self.config
        return OpenAICompatibleBackend(
            {
                "base_url": f"{active_config.base_url}/v1",
                "model": active_config.alias,
                "temperature": active_config.temperature,
                "timeout": active_config.timeout,
                "max_tokens": active_config.max_tokens,
                "context_size": active_config.context_size,
                "context_reserve_tokens": self.context_reserve_tokens,
                "image_min_tokens": active_config.image_min_tokens,
                "_runtime_diagnostics": runtime_diagnostics or {},
            }
        )

    @contextmanager
    def generation_session(self):
        owned, acquisition = self.process_manager.acquire(self.config, include_state=True)
        try:
            # Keep request-level sampling/token settings current while routing
            # through the authoritative manager's actual runtime port.
            runtime_config = replace(self.config, port=owned.config.port)
            yield self._client(runtime_config, {
                "model": self.config.requested_model,
                "gguf": str(self.config.model_path),
                "mmproj": str(self.config.mmproj_path),
                "pid": getattr(owned.process, "pid", "UNKNOWN"),
                "port": owned.config.port,
                "reused": bool(acquisition["reused"]),
                "restarted": bool(acquisition["restarted"]),
            })
        finally:
            self.process_manager.release(owned)

    def generate(self, instruction):
        self.validate_instruction(instruction)
        with self.generation_session() as client:
            return client.generate(instruction)
