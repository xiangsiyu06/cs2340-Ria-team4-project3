"""C1 pages: the degree progress form and its results.

Both are public: the site has no student accounts (only staff sign-in), and
nothing is saved. Both use GET, so a result is a plain link and "Edit courses"
only has to put the same values back into the form.
"""

from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .forms import DegreeProgressForm
from .services import match_requirements

FIELDS = list(DegreeProgressForm.base_fields)


@require_GET
def progress_form(request):
    """GET /planner/ - the form, filled in again when coming back from "Edit courses"."""
    form = DegreeProgressForm(initial={name: request.GET.get(name, '') for name in FIELDS})
    return render(request, 'planner/progress_form.html', {'form': form})


@require_GET
def progress_results(request):
    """GET /planner/results/?major=...&catalog_year=...&thread=...&courses=..."""
    if not any(name in request.GET for name in FIELDS):
        return redirect('planner:progress')
    form = DegreeProgressForm(request.GET)
    if not form.is_valid():
        return render(request, 'planner/progress_form.html', {'form': form})
    progress = match_requirements(form.cleaned_data['program'], form.cleaned_data['courses'])
    entered = {name: request.GET.get(name, '') for name in FIELDS}
    return render(request, 'planner/progress_results.html', {
        'progress': progress,
        'edit_url': f"{reverse('planner:progress')}?{urlencode(entered)}",
    })
