from django.urls import path

from .views import chat

app_name = "frontend"
urlpatterns = [path("", chat, name="chat")]
