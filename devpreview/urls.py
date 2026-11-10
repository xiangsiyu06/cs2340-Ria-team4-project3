from django.urls import include, path

from . import views

urlpatterns = [
    path("", include("frontend.urls")),
    path("api/chat/", views.unavailable),
    path("preview/", views.preview, name="preview"),
    path("preview/api/chat/", views.sample_answer),
    path("preview/source/", views.sample_source, name="sample-source"),
]
