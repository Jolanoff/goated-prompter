"""Request plumbing shared by workflow routes."""

from aiohttp import web

from ..backends.factory import canonical_backend_name
from ..contracts import GoatedPrompterRequest, as_bool
from ..workspace_store import text


def engine_request(state, config, settings, **fields):
    """Build a workflow's engine request with the saved prompt-engine selection.

    Configured remote/mock backends ignore local Director profiles.
    """
    configured = canonical_backend_name(config.get("backend")) in {"mock", "openai_compatible"}
    return GoatedPrompterRequest(
        prompt_model="Custom",
        director_profile="" if configured else text(
            settings.get("director_profile", state.saved_settings.get("selected_profile", "")),
            "Prompt engine", 512, optional=True),
        director_keep_model_loaded=as_bool(config.get("local_llama_cpp", {}).get("keep_model_loaded", False)),
        **fields,
    )


def active_job_conflict(state, message):
    """Return the 409 response for an occupied engine, or None. Call under admission."""
    active = state.active_job()
    if active:
        return web.json_response({"error": message, "active_job": active}, status=409)
    return None
