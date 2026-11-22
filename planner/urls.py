from django.urls import path

from . import views

app_name = 'planner'

urlpatterns = [
    # C1: degree progress check (Siyu)
    path('', views.progress_form, name='progress'),
    path('results/', views.progress_results, name='progress_results'),
]
