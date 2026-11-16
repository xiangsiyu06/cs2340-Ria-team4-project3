"""US3/US8: the question-answering endpoint used by the chat UI, plus a
staff-only preview of how the prompt is chosen for a question."""

import json
import logging
import time

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .llm import LLMUnavailable
from .planner import plan
from .prompts import build_messages, classify
from .retrieval import document_cards, with_neighbors
from .services import InvalidQuestion, answer, choose_intent, clean_question, retrieve_for

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

    history = conversation(request)
    try:
        result = answer(question, history)
    except InvalidQuestion as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except LLMUnavailable as exc:
        logger.error("Answer service unavailable: %s", exc)
        return JsonResponse(
            {"error": "The answer service is temporarily unavailable. Please try again in a moment."},
            status=503,
        )
    remember(request, history, question, result.text)
    return JsonResponse(result.as_dict())


# Follow-up questions ("how can I study it?") need the last few turns. They are
# kept in the visitor's session, expire after 30 minutes of inactivity, and
# can be cleared with POST /rag/reset/.
HISTORY_TURNS = 3
HISTORY_SECONDS = 30 * 60


def conversation(request):
    turns = request.session.get("rag_history", [])
    if turns and time.time() - turns[-1].get("t", 0) > HISTORY_SECONDS:
        return []
    return turns[-HISTORY_TURNS:]


def remember(request, history, question, text):
    request.session["rag_history"] = [*history, {"q": str(question)[:500], "a": text[:500], "t": time.time()}][-HISTORY_TURNS:]


@require_POST
def reset(request):
    """POST /rag/reset/ forgets the conversation (for a "New conversation" button)."""
    request.session.pop("rag_history", None)
    return JsonResponse({"ok": True})


@staff_member_required
@require_GET
def prompt_preview(request):
    """GET /rag/prompt-preview/?q=... shows the runtime prompt selection (US8).

    Returns the question type and who chose it (the planner, or the keyword
    rules as fallback), the planner's standalone question and search terms,
    the chunks retrieved, and the exact messages that would be sent to the
    model. One planner call is made; the answer call is not.
    """
    try:
        question = clean_question(request.GET.get("q", ""))
    except InvalidQuestion as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    cards = document_cards()
    planned = plan(question, (), cards)
    rules = classify(planned.question)
    intent = choose_intent(planned)
    hits = retrieve_for(planned.question, intent, planned)
    names = {source_id: line.split(" - key terms:")[0] for _, source_id, line in cards}
    chunks = with_neighbors(hits)
    return JsonResponse({
        "question": question,
        "standalone_question": planned.question,
        "documents_picked": [names.get(source_id, str(source_id)) for source_id in planned.document_ids],
        "search_terms": list(planned.search_terms),
        "off_topic": planned.off_topic,
        "question_type": intent.label,
        "intent": intent.key,
        "type_chosen_by": "planner" if planned.intent_key else "keyword rules",
        "keyword_rules_would_pick": rules.intent.key,
        "matched_rule": rules.rule,
        "matched_text": rules.matched,
        "retrieval_limit": intent.retrieval_limit,
        "temperature": intent.temperature,
        "retrieved": [
            {"score": hit.score, "source": hit.chunk.source.name, "section": hit.chunk.section}
            for hit in hits
        ],
        "messages": build_messages(planned.question, chunks, intent) if chunks else [],
    }, json_dumps_params={"indent": 2})
