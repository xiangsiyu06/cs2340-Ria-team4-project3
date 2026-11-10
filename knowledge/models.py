import os
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class DataSource(models.Model):
    """One catalog page or degree-requirement PDF that the RAG system learns from (US5).

    Other stories that need data sources must use this model instead of creating
    their own. See "Data model & ingestion contract (US5)" in CLAUDE.md.
    """

    class SourceType(models.TextChoices):
        CATALOG_URL = 'catalog_url', 'Catalog URL'
        PDF = 'pdf', 'PDF'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        INGESTING = 'ingesting', 'Ingesting'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'

    name = models.CharField(max_length=200)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    url = models.URLField(
        max_length=500,
        blank=True,
        help_text='Required for catalog URL sources. Leave empty for PDFs.',
    )
    file = models.FileField(
        upload_to='sources/',
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])],
        help_text='Required for PDF sources (.pdf only). Leave empty for catalog URLs.',
    )
    major = models.CharField(max_length=100)
    catalog_year = models.CharField(max_length=20, help_text='e.g. 2026-2027')
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive sources stay in the list but should not be used to answer questions.',
    )

    # Set by the ingestion pipeline (knowledge/services.py), not by the form.
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    last_ingested_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['major', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_source_type_display()})'

    @property
    def file_basename(self):
        return os.path.basename(self.file.name) if self.file else ''

    def clean(self):
        """A catalog URL source has a URL and no file; a PDF source has a file and no URL."""
        super().clean()
        errors = {}
        if self.source_type == self.SourceType.CATALOG_URL:
            if not self.url:
                errors['url'] = 'A catalog URL source needs a URL.'
            if self.file:
                errors['file'] = 'A catalog URL source cannot have an uploaded file.'
        elif self.source_type == self.SourceType.PDF:
            if not self.file:
                errors['file'] = 'A PDF source needs an uploaded PDF file.'
            if self.url:
                errors['url'] = 'A PDF source cannot have a URL.'
        if errors:
            raise ValidationError(errors)

    # Status helpers for the ingestion pipeline. Each one saves immediately so the
    # list page shows the current state even if ingestion crashes halfway.

    def mark_ingesting(self):
        self.status = self.Status.INGESTING
        self.save(update_fields=['status', 'updated_at'])

    def mark_ready(self):
        self.status = self.Status.READY
        self.last_ingested_at = timezone.now()
        self.last_error = ''
        self.save(update_fields=['status', 'last_ingested_at', 'last_error', 'updated_at'])

    def mark_failed(self, error):
        self.status = self.Status.FAILED
        self.last_error = str(error)
        self.save(update_fields=['status', 'last_error', 'updated_at'])


class Chunk(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField()
    text = models.TextField()
    section = models.CharField(max_length=255, blank=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    anchor = models.CharField(max_length=255, blank=True)
    vector = models.JSONField(default=dict, editable=False)

    class Meta:
        ordering = ["source_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["source", "position"], name="knowledge_chunk_position")
        ]

    @property
    def citation_url(self):
        if self.source.source_type == DataSource.SourceType.PDF:
            url = reverse("knowledge:source-pdf", args=[self.source_id])
            return f"{url}#page={self.page_number}"
        return self.source.url + (f"#{quote(self.anchor)}" if self.anchor else "")
