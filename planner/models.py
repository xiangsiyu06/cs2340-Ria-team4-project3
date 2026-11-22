"""Structured degree requirements used by C1 (progress check) and C2 (switching majors).

See "Degree requirements & matching contract (C1/C2)" in CLAUDE.md. Every
requirement points back to the knowledge.DataSource it was extracted from.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from knowledge.models import DataSource

from .courses import normalize_course_code


class DegreeProgramQuerySet(models.QuerySet):
    def available(self):
        """Programs a student can check: at least one requirement from an active source."""
        return self.filter(
            groups__source__is_active=True, groups__courses__isnull=False,
        ).distinct()


class DegreeProgram(models.Model):
    """One set of graduation requirements: a major, a catalog year, and optionally a thread.

    At Georgia Tech each thread or concentration has its own complete catalog
    page, so a program with a thread holds that page's full requirements.
    """

    major = models.CharField(max_length=100)
    catalog_year = models.CharField(max_length=20, help_text='e.g. 2026-2027')
    thread = models.CharField(
        max_length=200,
        blank=True,
        help_text='Thread or concentration, e.g. "Embedded Devices & Artificial Intelligence". '
                  'Leave empty for a major without one.',
    )

    objects = DegreeProgramQuerySet.as_manager()

    class Meta:
        ordering = ['major', '-catalog_year', 'thread']
        constraints = [
            models.UniqueConstraint(
                fields=['major', 'catalog_year', 'thread'], name='planner_unique_program'
            ),
        ]

    def __str__(self):
        label = f'{self.major} {self.catalog_year}'
        return f'{label}, {self.thread}' if self.thread else label

    def requirement_groups(self):
        """The requirements used for matching, in catalog order.

        Requirements from inactive sources are left out, the same rule the
        chatbot follows, and so are groups with no courses.
        """
        return (
            self.groups.filter(source__is_active=True, courses__isnull=False)
            .distinct()
            .select_related('source')
            .prefetch_related('courses')
            .order_by('position', 'id')
        )


class RequirementGroup(models.Model):
    """One requirement, such as "Major Requirements" or "Select one for Ethics"."""

    class Rule(models.TextChoices):
        ALL = 'all', 'Complete all listed courses'
        CHOOSE = 'choose', 'Choose N of the listed courses'
        CREDITS = 'credits', 'At least X credit hours from the listed courses'

    program = models.ForeignKey(DegreeProgram, on_delete=models.CASCADE, related_name='groups')
    name = models.CharField(max_length=200)
    rule = models.CharField(max_length=10, choices=Rule.choices)
    required_count = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Choose rule only: how many of the listed courses are needed.'
    )
    credit_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Credit hours this requirement is worth in the catalog. Required for the credits rule, '
                  'where it is the minimum to complete.',
    )
    position = models.PositiveIntegerField(default=0, help_text='Order on the source page.')

    # Where the requirement comes from. Deleting the source deletes its requirements.
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='requirement_groups')
    source_url = models.URLField(
        max_length=500, blank=True, help_text='Catalog sources: link to the exact page section, if known.'
    )
    page_number = models.PositiveIntegerField(null=True, blank=True, help_text='PDF sources: page number.')

    class Meta:
        ordering = ['program', 'position', 'id']

    def __str__(self):
        return f'{self.name} ({self.program})'

    def clean(self):
        super().clean()
        if self.rule == self.Rule.CHOOSE and not self.required_count:
            raise ValidationError({'required_count': 'Say how many courses the student must choose.'})
        if self.rule != self.Rule.CHOOSE and self.required_count:
            raise ValidationError({'required_count': 'Only the choose rule uses a course count.'})
        if self.rule == self.Rule.CREDITS and not self.credit_hours:
            raise ValidationError({'credit_hours': 'Say how many credit hours the student needs.'})

    @property
    def citation_url(self):
        """Link to the catalog section or PDF page this requirement was read from."""
        if self.source.source_type == DataSource.SourceType.PDF:
            url = reverse('knowledge:source-pdf', args=[self.source_id])
            return f'{url}#page={self.page_number}' if self.page_number else url
        return self.source_url or self.source.url

    def rule_summary(self, course_count):
        """Plain-English rule, e.g. "Choose 1 of 6 courses"."""
        if self.rule == self.Rule.ALL:
            return 'Complete this course' if course_count == 1 else f'Complete all {course_count} courses'
        if self.rule == self.Rule.CHOOSE:
            return f'Choose {self.required_count} of {course_count} courses'
        return f'At least {self.credit_hours} credit hours from {course_count} courses'


class RequirementCourse(models.Model):
    """A course listed in a requirement, with its credit hours when the catalog gives them."""

    group = models.ForeignKey(RequirementGroup, on_delete=models.CASCADE, related_name='courses')
    code = models.CharField(max_length=20, help_text='Course code, e.g. CS 1331.')
    credits = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Credit hours. Needed for courses in a credits rule.'
    )

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['group', 'code'], name='planner_unique_course_in_group'),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        super().clean()
        code = normalize_course_code(self.code)
        if code is None:
            raise ValidationError({'code': 'Enter a course code such as CS 1331.'})
        self.code = code
