"""Generic OpenAI-compatible chat-completions backend using the standard library."""

import base64
from collections import Counter
import hashlib
import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import BackendConfigurationError, BackendGenerationError, BackendRunawayError, GoatedPrompterBackend
from ..diagnostics import debug_prompts_enabled, log_request, log_response, payload_without_binary_images


RUNAWAY_STREAM_CHARACTER_LIMIT = 7000


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


def _response_text(payload, *, unlimited_tokens=False, hard_max_tokens=None):
    try:
        if payload["choices"][0].get("finish_reason") == "length":
            if hard_max_tokens:
                raise BackendRunawayError(
                    f"The prompt engine reached the workflow safety limit of {hard_max_tokens} tokens without "
                    "finishing. The model may be looping. Shorten the requested output or use a different engine."
                )
            if unlimited_tokens:
                raise BackendGenerationError(
                    "The prompt engine stopped at its context or server output limit. This request had no "
                    "application token cap. Increase the engine's context size or server output allowance, "
                    "or shorten the input, then retry. The incomplete prompt was not accepted."
                )
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


def _stream_part_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text", "output_text"}
        )
    return ""


def _repetition_issue(text):
    """Return a dominant repeated phrase when output has clearly degenerated."""
    words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", str(text or "").casefold())
    if len(words) < 120:
        return None
    for width, minimum in ((2, 12), (3, 8), (4, 6)):
        phrases = Counter(tuple(words[index:index + width]) for index in range(len(words) - width + 1))
        if not phrases:
            continue
        phrase, count = phrases.most_common(1)[0]
        # Measure how frequently the phrase restarts, rather than multiplying
        # by phrase width; the latter flags ordinary repeated sentence syntax.
        if count >= minimum and count / len(words) >= 0.12:
            return " ".join(phrase)
    return None


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
        self.activity_callback = settings.get("_activity_callback")
        # Set by the owned llama.cpp adapter, not inferred from arbitrary URLs.
        self.is_llama_cpp = settings.get("_is_llama_cpp") is True

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
        requested_hard_limit = getattr(instruction, "hard_max_tokens", None)
        hard_limit = (
            max(1, min(1048576, requested_hard_limit))
            if isinstance(requested_hard_limit, int) and requested_hard_limit > 0
            else None
        )
        unlimited = getattr(instruction, "unlimited_tokens", False)
        if hard_limit is not None:
            payload["max_tokens"] = hard_limit
        elif unlimited:
            # llama.cpp explicitly supports -1 (generate until EOS). Generic
            # OpenAI-compatible APIs instead use their own default when omitted;
            # sending a negative token count to those providers is not portable.
            if self.is_llama_cpp:
                payload["max_tokens"] = -1
            else:
                payload.pop("max_tokens")
        elif isinstance(override, int) and override > 0:
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
        streaming = self.activity_callback is not None
        if streaming:
            payload["stream"] = True
        log_request(self, instruction, payload)
        _log_multimodal_messages(payload["messages"])
        if streaming:
            safe = payload_without_binary_images(payload)
            self.emit_activity(
                "request",
                model=self.model,
                messages=safe.get("messages", []),
                parameters={key: value for key, value in safe.items() if key not in {"messages", "model"}},
                timeout_seconds=self.timeout,
            )
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if streaming else "application/json",
        }
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
                content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).casefold()
                if streaming and ("text/event-stream" in content_type or "ndjson" in content_type):
                    character_limit = getattr(instruction, "stream_character_limit", None)
                    if type(character_limit) is not int or not 0 < character_limit <= 1048576:
                        character_limit = RUNAWAY_STREAM_CHARACTER_LIMIT
                    result = self._stream_response(response, unlimited, hard_limit, character_limit)
                    log_response(instruction, result)
                    return result
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                error_payload = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
                detail = str(error_payload.get("error", {}).get("message", "")).strip()
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            message = f"OpenAI-compatible backend returned HTTP {exc.code}{suffix}"
            self.emit_activity("error", message=message)
            raise BackendGenerationError(message) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                message = (f"The prompt engine did not respond within {self.timeout:g} seconds. "
                           "Check that the engine is healthy, or increase its timeout before retrying.")
                self.emit_activity("error", message=message)
                raise BackendGenerationError(message) from exc
            message = f"Could not reach the OpenAI-compatible backend: {exc.reason}"
            self.emit_activity("error", message=message)
            raise BackendGenerationError(message) from exc
        except TimeoutError as exc:
            message = (f"The prompt engine did not respond within {self.timeout:g} seconds. "
                       "Check that the engine is healthy, or increase its timeout before retrying.")
            self.emit_activity("error", message=message)
            raise BackendGenerationError(message) from exc
        except OSError as exc:
            message = f"The connection to the prompt engine failed while reading its response: {exc}"
            self.emit_activity("error", message=message)
            raise BackendGenerationError(message) from exc
        except BackendGenerationError as exc:
            self.emit_activity("error", message=str(exc))
            raise

        try:
            response_payload = json.loads(body)
        except json.JSONDecodeError as exc:
            message = "OpenAI-compatible backend returned invalid JSON."
            self.emit_activity("error", message=message)
            raise BackendGenerationError(message) from exc
        try:
            result = _response_text(
                response_payload,
                unlimited_tokens=unlimited,
                hard_max_tokens=hard_limit,
            )
        except BackendGenerationError as exc:
            self.emit_activity("error", message=str(exc))
            raise
        if streaming:
            self.emit_activity("response_delta", text=result)
        if hard_limit and len(result) > hard_limit * 12:
            message = (
                f"The prompt engine exceeded the workflow safety limit "
                f"({len(result)} characters for a {hard_limit}-token request). "
                "The model appears to be looping."
            )
            self.emit_activity("error", message=message)
            raise BackendRunawayError(message)
        repeated = _repetition_issue(result)
        if hard_limit and repeated:
            message = (
                f'The prompt engine entered a repetition loop around "{repeated}". '
                "Generation was stopped before the output could be accepted."
            )
            self.emit_activity("error", message=message)
            raise BackendRunawayError(message)
        if streaming:
            self.emit_activity("response_complete", finish_reason=response_payload.get("choices", [{}])[0].get("finish_reason"))
        log_response(instruction, result)
        return result

    def _stream_response(self, response, unlimited, hard_max_tokens=None,
                         stream_character_limit=RUNAWAY_STREAM_CHARACTER_LIMIT):
        pieces = []
        streamed_characters = 0
        output_characters = 0
        hard_character_limit = hard_max_tokens * 12 if hard_max_tokens else None
        next_repetition_check = 1200
        finish_reason = None
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":") or line.startswith("event:"):
                continue
            data = line[5:].strip() if line.startswith("data:") else line
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError as exc:
                raise BackendGenerationError("OpenAI-compatible backend returned an invalid streaming event.") from exc
            if chunk.get("error"):
                detail = chunk["error"].get("message") if isinstance(chunk["error"], dict) else chunk["error"]
                raise BackendGenerationError(f"OpenAI-compatible backend stream failed: {detail}")
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            chunk_finish_reason = choice.get("finish_reason")
            delta = choice.get("delta") or {}
            reasoning = _stream_part_text(delta.get("reasoning_content") or delta.get("reasoning"))
            if reasoning:
                streamed_characters += len(reasoning)
                self.emit_activity("reasoning_delta", text=reasoning)
            text = _stream_part_text(delta.get("content"))
            if text:
                pieces.append(text)
                streamed_characters += len(text)
                output_characters += len(text)
                self.emit_activity("response_delta", text=text)
            if (hard_max_tokens and output_characters > stream_character_limit
                    and not chunk_finish_reason):
                raise BackendRunawayError(
                    f"The prompt engine exceeded {stream_character_limit:,} generated characters "
                    "without finishing. Generation was stopped so this prompt can be retried."
                )
            if hard_character_limit and streamed_characters > hard_character_limit:
                raise BackendRunawayError(
                    f"The prompt engine exceeded the workflow safety limit while streaming "
                    f"({streamed_characters} characters for a {hard_max_tokens}-token request). "
                    "The model appears to be looping, so generation was stopped."
                )
            if output_characters >= next_repetition_check:
                output = "".join(pieces)
                repeated = _repetition_issue(output)
                if repeated:
                    phrase = r"\b" + r"\W+".join(re.escape(word) for word in repeated.split()) + r"\b"
                    first_repeat = re.search(phrase, output, flags=re.IGNORECASE)
                    prefix = output[:first_repeat.start()] if first_repeat else ""
                    # Offer only text preceding the repeated pattern, never the
                    # looping tail. Dataset still validates this before use.
                    sentence_ends = list(re.finditer(r"[.!?](?=\s|$)", prefix))
                    prefix = prefix[:sentence_ends[-1].end()] if sentence_ends else ""
                    raise BackendRunawayError(
                        f'The prompt engine entered a repetition loop around "{repeated}". '
                        "Generation was stopped before the output could grow indefinitely.",
                        recoverable_text=prefix,
                    )
                next_repetition_check = output_characters + 400
            finish_reason = chunk_finish_reason or finish_reason
        result = "".join(pieces).strip()
        if finish_reason == "length":
            if hard_max_tokens:
                raise BackendRunawayError(
                    f"The prompt engine reached the workflow safety limit of {hard_max_tokens} tokens without "
                    "finishing. The model may be looping. Shorten the requested output or use a different engine."
                )
            if unlimited:
                raise BackendGenerationError(
                    "The prompt engine stopped at its context or server output limit. This request had no "
                    "application token cap. Increase the engine's context size or server output allowance, "
                    "or shorten the input, then retry. The incomplete prompt was not accepted."
                )
            raise BackendGenerationError(
                "Generation was truncated at the token limit. Increase max_tokens and context size, "
                "shorten the input, or select a shorter prompt length, then retry."
            )
        if not result:
            raise BackendGenerationError("OpenAI-compatible backend returned an empty prompt.")
        self.emit_activity("response_complete", finish_reason=finish_reason or "stop")
        return result
