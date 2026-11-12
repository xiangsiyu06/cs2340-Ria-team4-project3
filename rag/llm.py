"""Minimal chat-completion client for an OpenAI-compatible HTTPS endpoint.

Standard library only, so no provider SDK is added to requirements.txt. The
provider is chosen entirely in ``.env``:

    LLM_API_URL   chat-completions URL (default: Gemini's OpenAI-compatible endpoint)
    LLM_MODEL     model name (default: gemini-3.1-flash-lite; larger free quota than gemini-3.5-flash)
    LLM_API_KEY   bearer token
"""

import json
import logging
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
MAX_OUTPUT_TOKENS = 1024
# The chat UI gives up after 60 s, so two attempts must finish well inside that.
ATTEMPT_TIMEOUT_SECONDS = 22
RETRY_STATUSES = {429, 500, 502, 503, 504}


class LLMUnavailable(RuntimeError):
    """The model could not be reached or did not return usable text."""


def config():
    return {
        "url": os.getenv("LLM_API_URL", "").strip() or DEFAULT_API_URL,
        "model": os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
        "key": os.getenv("LLM_API_KEY", "").strip(),
        # Gemini 3.x "thinks" before answering unless told not to; thinking
        # tokens are slow and count against max_tokens. Leave empty for
        # providers that reject the field.
        "reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "none").strip(),
    }


def complete(messages, *, temperature=0.1):
    """Send ``messages`` (OpenAI chat format) and return the assistant's text."""
    settings = config()
    if not settings["key"]:
        raise LLMUnavailable("LLM_API_KEY is not set.")

    body = {
        "model": settings["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    if settings["reasoning_effort"]:
        body["reasoning_effort"] = settings["reasoning_effort"]
    request = Request(
        settings["url"],
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {settings['key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "DegreeGuide/1.0",
        },
        method="POST",
    )

    last_error = None
    for attempt in (1, 2):
        try:
            with urlopen(request, timeout=ATTEMPT_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
            return _text(payload)
        except HTTPError as exc:
            detail = exc.read(2000).decode(errors="replace")
            last_error = f"HTTP {exc.code} from {settings['model']}: {detail[:300]}"
            if exc.code not in RETRY_STATUSES:
                break
        except (URLError, socket.timeout, TimeoutError, OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("LLM attempt %s failed: %s", attempt, last_error)
    raise LLMUnavailable(last_error or "The model returned no answer.")


def _text(payload):
    try:
        text = payload["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LLMUnavailable("The model response had no choices.") from exc
    text = text.strip()
    if not text:
        raise LLMUnavailable("The model returned an empty answer.")
    return text
