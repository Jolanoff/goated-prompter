"""Generic OpenAI-compatible chat-completions backend using the standard library."""

import base64
import hashlib
import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import BackendConfigurationError, BackendGenerationError, GoatedPrompterBackend
from ..diagnostics import debug_prompts_enabled, log_request, log_response


def _image_url_descriptor(url):
    value = str(url or "")
    if value.startswith("data:") and "," in value:
        header, encoded = value.split(",", 1)
        try:
            payload = base64.b64decode(encoded, validate=False)
        except (ValueError, TypeError):
            payload = encoded.encode("utf-8", errors="replace")
        return f"{header},<redacted> sha256={hashlib.sha256(payload).hexdigest()}"
    return "<non-data image URL redacted>"


def _log_multimodal_messages(messages):
    if not debug_prompts_enabled():
        return
    if not any(
        isinstance(message.get("content"), list)
        and any(isinstance(part, dict) and part.get("type") == "image_url" for part in message["content"])
        for message in messages
    ):
        return
    print("[Goated Prompter FINAL LLM REQUEST]", flush=True)
    for index, message in enumerate(messages, start=1):
        print(f"MESSAGE {index} ROLE={str(message.get('role') or '').upper()}", flush=True)
        content = message.get("content")
        if isinstance(content, str):
            print(content, flush=True)
            continue
        for part_index, part in enumerate(content or (), start=1):
            if not isinstance(part, dict):
                print(f"PART {part_index}: {part}", flush=True)
            elif part.get("type") == "text":
                print(f"TEXT PART {part_index}:\n{part.get('text', '')}", flush=True)
            elif part.get("type") == "image_url":
                image_url = part.get("image_url") or {}
                print(
                    f"IMAGE PART {part_index}: {_image_url_descriptor(image_url.get('url'))}",
                    flush=True,
                )
            else:
                print(f"PART {part_index}: type={part.get('type')}", flush=True)


def _chat_completions_url(base_url):
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BackendConfigurationError("OpenAI-compatible base_url must be an http or https URL.")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def _response_text(payload):
    try:
        if payload["choices"][0].get("finish_reason") == "length":
            raise BackendGenerationError(
                "Generation was truncated at the token limit. Increase max_tokens and context size, "
                "shorten the input, or select a shorter prompt length, then retry."
            )
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BackendGenerationError("OpenAI-compatible response did not contain choices[0].message.content.") from exc

    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text", "output_text"}
        ).strip()
    else:
        text = ""

    if not text:
        raise BackendGenerationError("OpenAI-compatible backend returned an empty prompt.")
    return text


class OpenAICompatibleBackend(GoatedPrompterBackend):
    name = "openai_compatible"
    supports_vision = True

    def __init__(self, settings):
        self.url = _chat_completions_url(settings.get("base_url"))
        self.model = str(settings.get("model") or "").strip()
        if not self.model:
            raise BackendConfigurationError("OpenAI-compatible model is not configured.")

        api_key_env = str(settings.get("api_key_env") or "GOATED_PROMPTER_API_KEY").strip()
        self.api_key = str(settings.get("api_key") or os.environ.get(api_key_env, "")).strip()
        self.runtime_diagnostics = dict(settings.get("_runtime_diagnostics") or {})

        try:
            self.temperature = max(0.0, min(2.0, float(settings.get("temperature", 0.5))))
            self.timeout = max(1.0, min(3600.0, float(settings.get("timeout", 90))))
            self.max_tokens = max(1, min(1048576, int(settings.get("max_tokens", 768))))
            self.context_size = int(settings.get("context_size") or 0)
            self.context_reserve_tokens = max(1024, int(settings.get("context_reserve_tokens", 1024)))
            self.image_min_tokens = max(1, int(settings.get("image_min_tokens", 1024)))
        except (TypeError, ValueError) as exc:
            raise BackendConfigurationError("OpenAI-compatible temperature, timeout, or max_tokens is invalid.") from exc

    def generate(self, instruction):
        self.validate_instruction(instruction)
        payload = {
            "model": self.model,
            "messages": instruction.to_messages(),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        override = getattr(instruction, "max_tokens", None)
        if isinstance(override, int) and override > 0:
            budget = max(self.max_tokens, override)
            if self.context_size:
                # No model tokenizer is available: this is a coarse text estimate
                # plus explicit headroom, not an exact token-capacity guarantee.
                text_chars = 0
                image_count = 0
                for message in payload["messages"]:
                    content = message.get("content", "")
                    if isinstance(content, str):
                        text_chars += len(content)
                    else:
                        for part in content:
                            text_chars += len(part.get("text", ""))
                            image_count += int(part.get("type") == "image_url")
                estimated_input = math.ceil(text_chars / 4) + image_count * self.image_min_tokens
                available = self.context_size - estimated_input - self.context_reserve_tokens
                if available < override:
                    raise BackendConfigurationError(
                        f"Maximum Detail needs at least {override} output tokens, but context_size={self.context_size} "
                        f"leaves approximately {max(0, available)} after a coarse input estimate and "
                        f"{self.context_reserve_tokens} reserve tokens (no model tokenizer available). "
                        "Increase context size, shorten input/workflow rules, or select a shorter prompt length."
                    )
                budget = min(budget, available)
            payload["max_tokens"] = budget
        log_request(self, instruction, payload)
        _log_multimodal_messages(payload["messages"])
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                error_payload = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
                detail = str(error_payload.get("error", {}).get("message", "")).strip()
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            raise BackendGenerationError(f"OpenAI-compatible backend returned HTTP {exc.code}{suffix}") from exc
        except URLError as exc:
            raise BackendGenerationError(f"Could not reach the OpenAI-compatible backend: {exc.reason}") from exc
        except TimeoutError as exc:
            raise BackendGenerationError("OpenAI-compatible backend request timed out.") from exc

        try:
            response_payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise BackendGenerationError("OpenAI-compatible backend returned invalid JSON.") from exc
        result = _response_text(response_payload)
        log_response(instruction, result)
        return result
