"""US3: the question-answering endpoint used by the chat UI."""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .llm import LLMUnavailable
from .services import InvalidQuestion, answer

logger = logging.getLogger(__name__)


@require_POST
def ask(request):
    """POST /rag/ask/ with JSON {"question": "..."}; see docs/chat-api.md."""
    if request.content_type != "application/json":
        return JsonResponse({"error": "Send a JSON question."}, status=415)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    question = payload.get("question") if isinstance(payload, dict) else None

    try:
        result = answer(question)
    except InvalidQuestion as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except LLMUnavailable as exc:
        logger.error("Answer service unavailable: %s", exc)
        return JsonResponse(
            {"error": "The answer service is temporarily unavailable. Please try again in a moment."},
            status=503,
        )
    return JsonResponse(result.as_dict())
