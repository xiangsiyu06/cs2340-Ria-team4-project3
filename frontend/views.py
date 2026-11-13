from django.conf import settings
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET


@require_GET
def chat(request):
    return render(request, "frontend/chat.html", {
        "chat_api_url": getattr(settings, "DEGREEGUIDE_CHAT_API_URL", None) or reverse("rag:ask"),
    })
