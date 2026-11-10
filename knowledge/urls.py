from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.views import LoginView
from django.urls import path, reverse_lazy

from . import views

app_name = 'knowledge'

urlpatterns = [
    path(
        'login/',
        LoginView.as_view(
            template_name='knowledge/login.html',
            authentication_form=AdminAuthenticationForm,
            next_page=reverse_lazy('knowledge:source_list'),
        ),
        name='login',
    ),
    # US5: data source management (staff only)
    path('sources/', views.source_list, name='source_list'),
    path('sources/new/', views.source_create, name='source_create'),
    path('sources/<int:pk>/edit/', views.source_edit, name='source_edit'),
    path('sources/<int:pk>/delete/', views.source_delete, name='source_delete'),
    path('sources/<int:pk>/pdf/', views.source_pdf, name='source-pdf'),
    path('sources/<int:pk>/reingest/', views.source_reingest, name='source_reingest'),
]
