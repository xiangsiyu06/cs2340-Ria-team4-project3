"""Requirement matching shared by C1 (degree progress) and C2 (switching majors).

``match_requirements`` is the only matching logic in the project; C2 must call
it rather than write its own. It reads requirements from the database and
never writes, and it knows nothing about views or requests, so any caller
(page, test, shell) gets the same answer. See CLAUDE.md, "Degree
requirements & matching contract (C1/C2)".
"""

from dataclasses import dataclass

from .courses import read_courses
from .models import RequirementGroup

Rule = RequirementGroup.Rule

# Order in which requirements claim courses: the specific ones first, so an
# elective list never takes a course that a requirement names outright.
CLAIM_ORDER = {Rule.ALL: 0, Rule.CHOOSE: 1, Rule.CREDITS: 2}


@dataclass(frozen=True)
class SourceRef:
    """Where a requirement comes from, for the link shown next to it."""

    name: str              # DataSource.name
    url: str               # catalog page (section) or PDF link
    page: int | None       # PDF page number, if known


@dataclass(frozen=True)
class RequirementStatus:
    """How the student's courses meet one requirement."""

    group_id: int
    name: str
    rule: str                      # "all", "choose" or "credits"
    summary: str                   # e.g. "Choose 1 of 6 courses"
    satisfied: bool
    unit: str                      # "course" (all, choose) or "credit hour" (credits)
    required: int                  # courses or credit hours needed, in ``unit``
    completed: int                 # courses or credit hours counted, in ``unit``
    used_courses: tuple[str, ...]  # the student's courses counted here
    options: tuple[str, ...]       # listed courses not taken yet (for "all": exactly what is missing)
    credits_required: int | None   # credit hours this requirement is worth; None if unknown
    credits_earned: int | None     # credit hours earned toward it; None if unknown
    source: SourceRef

    @property
    def remaining(self):
        return max(self.required - self.completed, 0)


@dataclass(frozen=True)
class DegreeProgress:
    """Result of ``match_requirements`` for one program."""

    program: object                          # the planner.DegreeProgram that was checked
    requirements: tuple[RequirementStatus, ...]  # catalog order
    completed_courses: tuple[str, ...]       # normalized codes, as entered
    unrecognized: tuple[str, ...]            # input pieces that are not course codes
    unused_courses: tuple[str, ...]          # valid codes that count toward no requirement

    @property
    def satisfied(self):
        return tuple(r for r in self.requirements if r.satisfied)

    @property
    def still_needed(self):
        return tuple(r for r in self.requirements if not r.satisfied)

    @property
    def satisfied_count(self):
        return len(self.satisfied)

    @property
    def total_count(self):
        return len(self.requirements)

    @property
    def is_complete(self):
        return bool(self.requirements) and not self.still_needed

    @property
    def credits_required(self):
        """Total credit hours of the listed requirements, or None if any lacks credit data."""
        if not self.requirements or any(r.credits_required is None for r in self.requirements):
            return None
        return sum(r.credits_required for r in self.requirements)

    @property
    def credits_earned(self):
        if self.credits_required is None:
            return None
        return sum(r.credits_earned for r in self.requirements)


def match_requirements(program, completed_courses) -> DegreeProgress:
    """Check ``completed_courses`` against every requirement of ``program``.

    Args:
        program: a ``planner.models.DegreeProgram``.
        completed_courses: one string ("cs1331, CS-1332\\nMATH 1551") or an
            iterable of strings, in any common format. Pieces that are not
            course codes are returned in ``unrecognized``, not raised.

    Returns:
        A ``DegreeProgress``. Its ``requirements`` keep catalog order; use
        ``satisfied`` / ``still_needed`` for the two columns and
        ``credits_earned`` / ``credits_required`` for credit progress (None
        when the catalog data has no credit hours for some requirement).

    Rules:
        * all: every listed course is completed.
        * choose: ``required_count`` of the listed courses are completed.
        * credits: completed listed courses add up to ``credit_hours``
          (courses without credit data don't count).
        * Each course counts toward one requirement, except that a course
          several "all" requirements name satisfies each of them. "all"
          requirements claim their courses first, then "choose", then
          "credits"; within a rule, catalog order. The result does not
          depend on the order the courses were typed in.
        * Only requirements from active sources are used.
    """
    codes, unrecognized = read_courses(completed_courses)
    taken = set(codes)
    groups = list(program.requirement_groups())
    claimed = set()
    statuses = {}
    for group in sorted(groups, key=lambda g: CLAIM_ORDER[g.rule]):  # stable: catalog order within a rule
        statuses[group.pk] = _check(group, taken, claimed)
    return DegreeProgress(
        program=program,
        requirements=tuple(statuses[group.pk] for group in groups),
        completed_courses=tuple(codes),
        unrecognized=tuple(unrecognized),
        unused_courses=tuple(code for code in codes if code not in claimed),
    )


def _check(group, taken, claimed):
    """Status of one requirement. Adds the courses it uses to ``claimed``."""
    courses = list(group.courses.all())
    listed = [course.code for course in courses]
    credits = {course.code: course.credits for course in courses}

    if group.rule == Rule.ALL:
        used = [code for code in listed if code in taken]
        required, completed, unit = len(listed), len(used), 'course'
    elif group.rule == Rule.CHOOSE:
        free = [code for code in listed if code in taken and code not in claimed]
        used = free[: group.required_count]
        required, completed, unit = group.required_count, len(used), 'course'
    else:  # credits
        used, completed = [], 0
        for code in listed:
            if completed >= group.credit_hours:
                break
            if code in taken and code not in claimed and credits[code]:
                used.append(code)
                completed += credits[code]
        required, unit = group.credit_hours, 'credit hour'
    claimed.update(used)

    satisfied = completed >= required
    credits_required, credits_earned = _credit_hours(group, listed, credits, used, completed, required, satisfied)
    return RequirementStatus(
        group_id=group.pk,
        name=group.name,
        rule=group.rule,
        summary=group.rule_summary(len(listed)),
        satisfied=satisfied,
        unit=unit,
        required=required,
        completed=completed,
        used_courses=tuple(used),
        options=tuple(code for code in listed if code not in taken),
        credits_required=credits_required,
        credits_earned=credits_earned,
        source=SourceRef(name=group.source.name, url=group.citation_url, page=group.page_number),
    )


def _credit_hours(group, listed, credits, used, completed, required, satisfied):
    """(worth, earned) in credit hours for one requirement, or (None, None) without data."""
    worth = group.credit_hours
    if worth is None and group.rule == Rule.ALL and all(credits[code] is not None for code in listed):
        worth = sum(credits[code] for code in listed)
    if worth is None:
        return None, None
    if satisfied:
        return worth, worth
    if group.rule == Rule.CREDITS:
        earned = completed
    elif group.rule == Rule.ALL and all(credits[code] is not None for code in used):
        earned = sum(credits[code] for code in used)
    else:
        # Choose N courses worth X hours: each chosen course is worth X / N.
        earned = round(worth * completed / required) if required else 0
    return worth, min(earned, worth)
