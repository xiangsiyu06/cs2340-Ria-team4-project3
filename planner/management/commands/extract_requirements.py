"""python manage.py extract_requirements [source_id] [--thread NAME] [--batch-chars N]

C1: turn one imported DataSource into planner requirements with the team's LLM.
Run it without a source id to list the sources. Running it again for the same
source replaces that source's earlier results.
"""

from django.core.management.base import BaseCommand, CommandError

from knowledge.models import DataSource
from planner.extraction import BATCH_CHARS, ExtractionError, extract_requirements


class Command(BaseCommand):
    help = "Extract structured degree requirements (C1/C2) from an imported data source using the LLM."

    def add_arguments(self, parser):
        parser.add_argument("source_id", nargs="?", type=int, help="DataSource id. Omit it to list the sources.")
        parser.add_argument(
            "--thread",
            help='Thread or concentration name. Default: read from a "Thread: ..." heading, else none. '
                 'Pass --thread "" for none.',
        )
        parser.add_argument(
            "--batch-chars", type=int, default=BATCH_CHARS,
            help=f"Characters of source text per model call (default {BATCH_CHARS}).",
        )

    def handle(self, *args, source_id=None, thread=None, batch_chars=BATCH_CHARS, **options):
        if source_id is None:
            self.list_sources()
            return
        source = DataSource.objects.filter(pk=source_id).first()
        if source is None:
            raise CommandError(f"There is no data source with id {source_id}. Run the command without an id to list them.")
        if not source.is_active:
            self.stdout.write(self.style.WARNING(
                f'"{source.name}" is inactive: its requirements are saved but not shown until it is active again.'
            ))

        try:
            result = extract_requirements(source, thread=thread, batch_chars=batch_chars)
        except ExtractionError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f'Saved {result.groups} requirements ({result.courses} courses) for "{result.program}" '
            f'from "{source.name}".'
        ))
        for note in result.skipped:
            self.stdout.write(f"  skipped: {note}")
        self.stdout.write("Check them in the admin: Planner > Requirement groups.")

    def list_sources(self):
        sources = DataSource.objects.order_by("pk")
        if not sources:
            self.stdout.write("No data sources yet. Add one on /knowledge/sources/ and re-ingest it.")
            return
        for source in sources:
            self.stdout.write(
                f"{source.pk:>4}  {source.get_status_display():<9}  {source.chunks.count():>4} chunks  "
                f"{source.major} {source.catalog_year}  {source.name}"
            )
