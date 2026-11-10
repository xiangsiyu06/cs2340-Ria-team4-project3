"""Fixed fixtures for exercising the UI, never registered by frontend.urls."""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST


@require_GET
def preview(request):
    return render(request, "frontend/chat.html", {
        "is_preview": True,
        "chat_api_url": "/preview/api/chat/",
    })


@require_POST
def unavailable(request):
    return JsonResponse({"error": "The live question service is not connected yet. Please try again later."}, status=503)


@require_POST
def sample_answer(request):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Send a JSON question."}, status=415)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    question = payload.get("question") if isinstance(payload, dict) else None
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        return JsonResponse({"error": "Enter a question between 1 and 2,000 characters."}, status=400)
    return JsonResponse({
        "answer": (
            "This is a sample response for the UI preview, not academic advice. "
            "The connected DegreeGuide will retrieve information from the team's dataset to answer your question.\n\n"
            "Each answer has its own sources. Expand the sample document below to inspect an excerpt and open the original."
        ),
        "question_type": "UI preview",
        "sources": [{
            "title": "DegreeGuide sample document",
            "url": reverse("sample-source"),
            "page": 1,
            "excerpt": "Source cards help you check an answer against its original document.",
        }],
    })


@require_GET
def sample_source(request):
    return render(request, "frontend/sample-source.html")
