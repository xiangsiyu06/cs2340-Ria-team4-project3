import logging
from functools import partial

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe

from .forms import DataSourceForm
from .models import DataSource
from .services import ingest_source

logger = logging.getLogger(__name__)
staff_only = partial(staff_member_required, login_url="knowledge:login")

# Editing any of these changes what gets ingested, so the old import is out of date.
CONTENT_FIELDS = {'source_type', 'url', 'file'}


@staff_only
def source_list(request):
    sources = DataSource.objects.all()
    return render(request, 'knowledge/source_list.html', {'sources': sources})


@staff_only
def source_create(request):
    if request.method == 'POST':
        form = DataSourceForm(request.POST, request.FILES)
        if form.is_valid():
            source = form.save()
            messages.success(request, f'Added "{source.name}". Click Re-ingest to import it.')
            return redirect('knowledge:source_list')
    else:
        form = DataSourceForm()
    return render(request, 'knowledge/source_form.html', {'form': form, 'is_new': True})


@staff_only
def source_edit(request, pk):
    source = get_object_or_404(DataSource, pk=pk)
    old_file_name = source.file.name
    if request.method == 'POST':
        form = DataSourceForm(request.POST, request.FILES, instance=source)
        if form.is_valid():
            source = form.save(commit=False)
            if CONTENT_FIELDS & set(form.changed_data):
                source.status = DataSource.Status.PENDING
            source.save()
            # Remove the old PDF if it was replaced or cleared, so uploads don't pile up on disk.
            if old_file_name and old_file_name != source.file.name:
                source.file.storage.delete(old_file_name)
            messages.success(request, f'Saved "{source.name}".')
            return redirect('knowledge:source_list')
    else:
        form = DataSourceForm(instance=source)
    return render(request, 'knowledge/source_form.html', {'form': form, 'is_new': False})


@staff_only
def source_delete(request, pk):
    source = get_object_or_404(DataSource, pk=pk)
    if request.method == 'POST':
        name = source.name
        file_name = source.file.name
        storage = source.file.storage
        source.delete()
        if file_name:
            storage.delete(file_name)
        messages.success(request, f'Deleted "{name}".')
        return redirect('knowledge:source_list')
    return render(request, 'knowledge/source_confirm_delete.html', {'source': source})


@staff_only
@require_POST
def source_reingest(request, pk):
    source = get_object_or_404(DataSource, pk=pk)
    try:
        ingest_source(source)
    except NotImplementedError as exc:
        source.mark_failed(f'NotImplementedError: {exc}')
        messages.warning(request, f'Re-ingest failed for "{source.name}": {exc}')
    except Exception as exc:
        logger.exception('Ingestion failed for DataSource %s', source.pk)
        source.mark_failed(f'{type(exc).__name__}: {exc}')
        messages.error(request, f'Re-ingest failed for "{source.name}": {exc}')
    else:
        # ingest_source records its own result, so read it back from the database.
        source.refresh_from_db()
        if source.status == DataSource.Status.FAILED:
            messages.error(request, f'Re-ingest failed for "{source.name}": {source.last_error}')
        elif source.status == DataSource.Status.READY:
            messages.success(request, f'Re-ingested "{source.name}". Status: {source.get_status_display()}.')
        else:
            messages.info(request, f'Current status for "{source.name}": {source.get_status_display()}.')
    return redirect('knowledge:source_list')


@require_safe
def source_pdf(request, pk):
    source = get_object_or_404(
        DataSource, pk=pk, source_type=DataSource.SourceType.PDF,
        status=DataSource.Status.READY, is_active=True,
    )
    if not source.file:
        raise Http404
    try:
        uploaded = source.file.open("rb")
    except OSError as exc:
        raise Http404 from exc
    response = FileResponse(
        uploaded, filename=source.file_basename, content_type="application/pdf", as_attachment=True,
    )
    response.headers["Content-Security-Policy"] = "sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
