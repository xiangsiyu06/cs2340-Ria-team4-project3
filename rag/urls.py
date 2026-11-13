from django.urls import path

from . import views

app_name = "rag"

urlpatterns = [
    # US3: grounded question answering, called by the chat UI
    path("ask/", views.ask, name="ask"),
    # Forget the conversation used for follow-up questions
    path("reset/", views.reset, name="reset"),
    # US8: staff-only view of the intent and prompt chosen for a question
    path("prompt-preview/", views.prompt_preview, name="prompt_preview"),
]
