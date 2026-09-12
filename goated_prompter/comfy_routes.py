"""Optional ComfyUI HTTP route used by the Generate button."""

import asyncio

from .backends.base import GoatedPrompterError
from .backends.llama_cpp_process import get_process_manager
from .config import load_config
from .core import GoatedPrompterRequest, GoatedPrompterService
from .director_profiles import discover_director_profiles
from .presets import (
    DEFAULT_DIRECTOR_PRESET,
    DirectorLibraryError,
    delete_user_director,
    list_director_presets,
    resolve_user_director_directory,
    save_user_director,
)

ROUTE_PATH = "/goated-prompter/v1/generate"
TEXT_ROUTE_PATH = "/goated-prompter/v1/generate-text"
MODELS_ROUTE_PATH = "/goated-prompter/v1/models"
PRESETS_ROUTE_PATH = "/goated-prompter/v1/presets"
UNLOAD_ROUTE_PATH = "/goated-prompter/v1/unload"


def register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return False

    @PromptServer.instance.routes.post(ROUTE_PATH)
    async def generate_prompt(request):
        try:
            payload = await request.json()
            director_request = GoatedPrompterRequest.from_mapping(payload)
            result = await asyncio.to_thread(GoatedPrompterService().generate, director_request)
            return web.json_response({
                "ok": True,
                "prompt": result.prompt,
                "backend": result.backend_name,
                "director_profile": result.director_profile,
                "prompt_model": result.prompt_model,
                "director_preset": result.director_preset,
            })
        except (ValueError, GoatedPrompterError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "Goated Prompter generation failed unexpectedly."},
                status=500,
            )

    @PromptServer.instance.routes.get(MODELS_ROUTE_PATH)
    async def list_director_models(request):
        try:
            config = load_config()
            settings = config.get("local_llama_cpp", {}) if isinstance(config, dict) else {}
            refresh = str(request.query.get("refresh") or "").strip().lower() in {"1", "true", "yes"}
            result = await asyncio.to_thread(discover_director_profiles, settings, refresh)
            payload = result.to_public_mapping()
            payload.update({
                "ok": True,
                "backend": str(config.get("backend") or "auto") if isinstance(config, dict) else "auto",
            })
            return web.json_response(payload)
        except (ValueError, GoatedPrompterError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "Goated Prompter model discovery failed unexpectedly."},
                status=500,
            )

    @PromptServer.instance.routes.get(PRESETS_ROUTE_PATH)
    async def list_presets(request):
        presets, warnings = await asyncio.to_thread(list_director_presets)
        return web.json_response({
            "ok": True,
            "default": DEFAULT_DIRECTOR_PRESET,
            "presets": presets,
            "warnings": warnings,
            "storage": str(resolve_user_director_directory()),
        })

    @PromptServer.instance.routes.post(PRESETS_ROUTE_PATH)
    async def save_preset(request):
        try:
            payload = await request.json()
            director, path = await asyncio.to_thread(
                save_user_director,
                payload.get("name"),
                payload.get("instructions"),
                payload.get("recommended_mode"),
            )
            return web.json_response({
                "ok": True,
                "director": director.to_public_mapping(),
                "file": path.name,
            })
        except (DirectorLibraryError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "The user Director could not be saved."},
                status=500,
            )

    @PromptServer.instance.routes.delete(PRESETS_ROUTE_PATH)
    async def delete_preset(request):
        try:
            payload = await request.json()
            director, path = await asyncio.to_thread(
                delete_user_director,
                payload.get("name") or payload.get("id"),
            )
            return web.json_response({
                "ok": True,
                "director": director.to_public_mapping(),
                "file": path.name,
            })
        except (DirectorLibraryError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "The user Director could not be deleted."},
                status=500,
            )

    @PromptServer.instance.routes.post(TEXT_ROUTE_PATH)
    async def generate_text_prompt(request):
        try:
            payload = await request.json()
            director_request = GoatedPrompterRequest.from_mapping(payload)
            result = await asyncio.to_thread(
                GoatedPrompterService().generate_text_only,
                director_request,
            )
            return web.json_response({
                "ok": True,
                "prompt": result.prompt,
                "backend": result.backend_name,
                "director_profile": result.director_profile,
                "prompt_model": result.prompt_model,
                "director_preset": result.director_preset,
            })
        except (ValueError, GoatedPrompterError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "Goated Prompter text generation failed unexpectedly."},
                status=500,
            )

    @PromptServer.instance.routes.post(UNLOAD_ROUTE_PATH)
    async def unload_model(request):
        try:
            status = await asyncio.to_thread(get_process_manager().request_unload)
            messages = {
                "idle": "No Goated Prompter model is currently loaded.",
                "pending": "Unload queued until the active Goated Prompter operation finishes.",
                "unloaded": "Goated Prompter model unloaded.",
            }
            return web.json_response({
                "ok": True,
                "status": status,
                "message": messages[status],
            })
        except Exception:
            return web.json_response(
                {"ok": False, "error": "The Goated Prompter model could not be unloaded safely."},
                status=500,
            )

    return True
