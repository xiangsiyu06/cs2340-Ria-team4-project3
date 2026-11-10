from django.contrib import admin

from .models import DataSource


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'source_type', 'major', 'catalog_year',
        'is_active', 'status', 'last_ingested_at',
    )
    list_filter = ('source_type', 'status', 'is_active', 'major')
    search_fields = ('name', 'major', 'url')
    readonly_fields = ('created_at', 'updated_at')
