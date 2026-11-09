import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import DataSourceForm
from .models import DataSource
from .services import ingest_source

logger = logging.getLogger(__name__)

# Editing any of these changes what gets ingested, so the old import is out of date.
CONTENT_FIELDS = {'source_type', 'url', 'file'}


@staff_member_required
def source_list(request):
    sources = DataSource.objects.all()
    return render(request, 'knowledge/source_list.html', {'sources': sources})


@staff_member_required
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


@staff_member_required
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


@staff_member_required
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


@staff_member_required
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
        else:
            messages.success(request, f'Re-ingested "{source.name}". Status: {source.get_status_display()}.')
    return redirect('knowledge:source_list')
