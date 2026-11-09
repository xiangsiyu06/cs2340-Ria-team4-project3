"""Ingestion entry point for the knowledge base.

US5 (Siyu) defines this interface. US6/US7 (Yongyi) implement it.
"""

from .models import DataSource


def ingest_source(source: DataSource) -> None:
    """Import one data source into the knowledge base.

    Called by the "Re-ingest" button on /knowledge/sources/ (staff only).

    What the real implementation (US6/US7) should do:

    1. Call ``source.mark_ingesting()`` first, so the list page shows that work
       has started.
    2. Load the raw content:
       - ``source.source_type == DataSource.SourceType.CATALOG_URL``: fetch and
         scrape ``source.url``.
       - ``source.source_type == DataSource.SourceType.PDF``: read the uploaded
         file at ``source.file`` (``source.file.open('rb')``).
    3. Clean and preprocess the text (US7), then replace any previously
       imported data for this source with the new data. Anything stored in the
       database should have a ForeignKey to ``DataSource`` with
       ``on_delete=models.CASCADE`` so that deleting a source removes it.
    4. On success: call ``source.mark_ready()``. It sets ``status = 'ready'``,
       sets ``last_ingested_at`` to now, and clears ``last_error``.
    5. On failure: call ``source.mark_failed(error_message)``. It sets
       ``status = 'failed'`` and stores the message in ``last_error``. Re-raising
       the exception afterwards is fine. The re-ingest view catches every
       exception, records it with ``mark_failed``, and shows it to the user.

    Never leave a source in ``'ingesting'`` when this function returns or raises.

    Until US6/US7 lands, this placeholder marks the source as ingesting and then
    raises ``NotImplementedError``. The view turns that into ``status = 'failed'``.
    """
    source.mark_ingesting()
    raise NotImplementedError(
        'Ingestion is not implemented yet (US6/US7).'
    )
