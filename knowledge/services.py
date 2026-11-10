"""US5 ingestion contract and query-side handoff for published chunks."""

import logging
import re
from collections import Counter

from django.db import transaction

from .extraction import MAX_PDF_BYTES, IngestionError, catalog_url, fetch_html, html_sections, pdf_sections
from .models import Chunk, DataSource
from .preprocessing import prepare_chunks

logger = logging.getLogger(__name__)


def term_vector(text):
    """Encode a sparse word-count vector for the initial local index."""
    normalized = re.sub(r"\b([a-z]{2,5})\s*(\d{4})\b", r"\1\2", text.lower())
    return dict(Counter(re.findall(r"[a-z0-9]+", normalized)))


def published_chunks():
    return Chunk.objects.filter(
        source__is_active=True, source__status=DataSource.Status.READY,
    ).select_related("source")


def source_sections(source):
    if source.source_type == DataSource.SourceType.CATALOG_URL:
        _, sections = html_sections(fetch_html(catalog_url(source.url)))
        return sections
    if source.source_type == DataSource.SourceType.PDF:
        if not source.file:
            raise IngestionError("Upload a PDF before re-ingesting this source.")
        try:
            with source.file.open("rb") as uploaded:
                data = uploaded.read(MAX_PDF_BYTES + 1)
        except OSError as exc:
            raise IngestionError("The uploaded PDF could not be opened. Upload it again.") from exc
        return pdf_sections(data)
    raise IngestionError("Choose a supported source type.")


def ingest_source(source: DataSource) -> None:
    """Replace this source's chunks atomically, recording its ingestion outcome."""
    source.refresh_from_db()
    with transaction.atomic():
        available = DataSource.objects.filter(pk=source.pk, updated_at=source.updated_at)
        available = available.exclude(status=DataSource.Status.INGESTING)
        if not available.update(status=DataSource.Status.INGESTING):
            return
        source.mark_ingesting()

    # Content edits invalidate a fetch in progress. Name, major and activation
    # edits do not, and are preserved by the status helpers' partial updates.
    attempt = DataSource.objects.filter(
        pk=source.pk, status=DataSource.Status.INGESTING,
        source_type=source.source_type, url=source.url, file=source.file.name or "",
    )
    try:
        sections = prepare_chunks(source_sections(source))
        if not sections:
            raise IngestionError(
                "The source contains no readable text. Check the page or use a PDF with a text layer."
            )
        chunks = [
            Chunk(
                source=source, position=index, text=section.text, section=section.heading[:255],
                page_number=section.page_number, anchor=section.anchor[:255],
                vector=term_vector(section.text),
            )
            for index, section in enumerate(sections)
        ]
        with transaction.atomic():
            if not attempt.update(status=DataSource.Status.INGESTING):
                return
            source.chunks.all().delete()
            Chunk.objects.bulk_create(chunks)
            source.mark_ready()
    except Exception as exc:
        if isinstance(exc, IngestionError):
            message = str(exc)
        else:
            logger.exception("Could not ingest DataSource %s", source.pk)
            message = "Could not finish this import. Check the source and retry."
        with transaction.atomic():
            if attempt.update(status=DataSource.Status.INGESTING):
                source.mark_failed(message)
