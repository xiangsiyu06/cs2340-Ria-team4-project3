from django.urls import path
from django.views.generic import RedirectView

urlpatterns = [path('', RedirectView.as_view(pattern_name='frontend:chat', permanent=False))]
