from django.urls import path

from . import views

app_name = 'knowledge'

urlpatterns = [
    # US5: data source management (staff only)
    path('sources/', views.source_list, name='source_list'),
    path('sources/new/', views.source_create, name='source_create'),
    path('sources/<int:pk>/edit/', views.source_edit, name='source_edit'),
    path('sources/<int:pk>/delete/', views.source_delete, name='source_delete'),
    path('sources/<int:pk>/pdf/', views.source_pdf, name='source-pdf'),
    path('sources/<int:pk>/reingest/', views.source_reingest, name='source_reingest'),
]
