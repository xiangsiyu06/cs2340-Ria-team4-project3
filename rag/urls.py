from django.urls import path

from . import views

app_name = "rag"

urlpatterns = [
    # US3: grounded question answering, called by the chat UI
    path("ask/", views.ask, name="ask"),
]
