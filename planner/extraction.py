"""C1: read structured degree requirements out of an imported DataSource.

The source's imported text (``knowledge.Chunk`` rows, from US6/US7) is sent to
the team's LLM (``rag.llm.complete``) a few passages at a time. The model's
JSON is checked and normalized here, and nothing is saved until every batch
has succeeded. Saving replaces whatever was extracted from this source before.
"""

import json
import re
import time
from dataclasses import dataclass, field

from django.db import transaction

from knowledge.models import DataSource
from rag.llm import LLMUnavailable, complete

from .courses import normalize_course_code
from .models import DegreeProgram, RequirementCourse, RequirementGroup

Rule = RequirementGroup.Rule

# rag.llm caps each reply at 1024 tokens, so a few passages are sent at a time.
BATCH_CHARS = 3000
# The free Gemini tier allows 15 requests a minute.
PAUSE_SECONDS = 4
# GT catalog headings name the thread, e.g. "... Computer Science - Thread: Media & People".
THREAD_HEADING = re.compile(r"\b(?:Thread|Concentration)s?\s*:\s*(.+)$", re.IGNORECASE)

PROMPT = """You turn Georgia Tech degree requirements into structured data. You get numbered passages from one official catalog page or degree-requirement PDF, often a table with the columns Code | Title | Credit Hours.

Reply with JSON only:
{"requirements": [{"name": "Major Requirements", "rule": "all", "count": null, "credits": 6, "courses": [["CS 2340", 3], ["CS 1332", 3]], "passage": 2}]}

- name: the requirement's heading or label in the source. If the label is generic ("Select one of the following"), add what it is for, e.g. "Statistics: select one".
- rule: "all" when every listed course is required; "choose" when the student picks some of the listed courses ("Select one of the following", "or"); "credits" when the student needs some number of credit hours from the listed courses.
- count: for "choose", how many courses to pick ("Select three" = 3). Otherwise null.
- credits: the credit hours the requirement is worth, as the source states it. For "credits", the hours needed. null if not stated.
- courses: every listed course as [code, credit hours]. Write codes as subject and number, like "MATH 1551". Use null for credit hours the source doesn't give.
- passage: the number of the passage that states the requirement.
- A course with "or" alternatives below it ("CS 2050 ... or CS 2051") becomes its own "choose" requirement with count 1 that lists all the alternatives; leave those courses out of the surrounding "all" requirement.
- Small numbers right after a title or label ("Objects and Design 1", "Select one: 1,4") are footnote markers, not credit hours. Credit hours are in the last column.
- Leave out requirements that name no specific course, such as "Free Electives", "Any HUM", or "Lab Science". Leave out options that combine several courses ("ISYE 2027 & ISYE 3030").
- Passages can overlap. List each requirement once.
- Use only what the passages say. If they contain no course requirements, reply {"requirements": []}."""


class ExtractionError(Exception):
    """Extraction could not finish. Nothing was saved and earlier results are kept."""


@dataclass
class Draft:
    """One requirement read from the model's reply, checked but not saved yet."""

    name: str
    rule: str
    required_count: int | None
    credit_hours: int | None
    courses: dict                 # code -> credit hours (or None), in listed order
    source_url: str = ""
    page_number: int | None = None


@dataclass
class ExtractionResult:
    program: DegreeProgram
    groups: int
    courses: int
    skipped: list = field(default_factory=list)  # what was left out, and why


def extract_requirements(source, *, thread=None, batch_chars=BATCH_CHARS):
    """Extract ``source``'s requirements and save them, replacing earlier ones.

    ``thread`` names the thread/concentration; by default it is read from a
    "Thread: ..." heading in the source, else left empty. Raises
    ``ExtractionError`` when the source has no imported text, the model can't
    be reached or replies with something unusable, or no requirement is found.
    """
    if source.status != DataSource.Status.READY:
        raise ExtractionError(f'"{source.name}" is not imported yet. Re-ingest it on the sources page first.')
    chunks = list(source.chunks.order_by("position"))
    if not chunks:
        raise ExtractionError(f'"{source.name}" has no imported text. Re-ingest it on the sources page first.')
    if thread is None:
        thread = detect_thread(chunks)

    drafts, skipped = [], []
    for number, batch in enumerate(batches(chunks, batch_chars)):
        if number:
            time.sleep(PAUSE_SECONDS)
        for item in ask_model(source, batch):
            draft = to_draft(item, source, batch, skipped)
            if draft is not None:
                merge(drafts, draft)
    if not drafts:
        raise ExtractionError("No course requirements were found in this source. Earlier results were kept.")

    program = save(source, thread.strip(), drafts)
    return ExtractionResult(program, len(drafts), sum(len(d.courses) for d in drafts), skipped)


def detect_thread(chunks):
    for chunk in chunks:
        match = THREAD_HEADING.search(chunk.section)
        if match:
            return match[1].strip()[:200]
    return ""


def batches(chunks, limit):
    """Consecutive chunks, about ``limit`` characters per batch (at least one chunk each)."""
    batch, size = [], 0
    for chunk in chunks:
        if batch and size + len(chunk.text) > limit:
            yield batch
            batch, size = [], 0
        batch.append(chunk)
        size += len(chunk.text)
    if batch:
        yield batch


def ask_model(source, batch):
    """The model's list of requirement objects for one batch of chunks."""
    passages = "\n\n".join(
        f"[{number}] Section: {chunk.section or '-'}"
        + (f" (page {chunk.page_number})" if chunk.page_number else "")
        + f"\n{chunk.text}"
        for number, chunk in enumerate(batch, 1)
    )
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": (
            f"Program: {source.major}, catalog year {source.catalog_year}\n\nPassages:\n{passages}"
        )},
    ]
    try:
        text = complete(messages, temperature=0.0)
    except LLMUnavailable as exc:
        raise ExtractionError(f"The model could not be reached: {exc}") from exc
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
    except ValueError:
        raise ExtractionError(
            "The model's reply was not valid JSON (it may have been cut off). Retry with a smaller --batch-chars."
        ) from None
    items = data.get("requirements") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ExtractionError('The model\'s reply had no "requirements" list.')
    return items


def hours(value):
    """A whole number of credit hours (or a count), or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def to_draft(item, source, batch, skipped):
    """Check one item of the model's reply. Returns a Draft, or None after noting why in ``skipped``."""
    if not isinstance(item, dict):
        skipped.append("an entry that was not a JSON object")
        return None
    name = " ".join(str(item.get("name") or "").split())[:200]
    rule = str(item.get("rule") or "").strip().lower()
    label = name or "(no name)"
    if not name or rule not in Rule.values:
        skipped.append(f"{label}: missing name or unknown rule {rule!r}")
        return None

    courses = {}
    for entry in item.get("courses") or []:
        if isinstance(entry, (list, tuple)) and entry:
            raw, credits = entry[0], entry[1] if len(entry) > 1 else None
        elif isinstance(entry, dict):
            raw, credits = entry.get("code"), entry.get("credits")
        else:
            raw, credits = entry, None
        code = normalize_course_code(str(raw or ""))
        if code is None:
            skipped.append(f"{label}: ignored {raw!r}, not a course code")
            continue
        courses.setdefault(code, hours(credits))
    if not courses:
        skipped.append(f"{label}: no course codes")
        return None

    count, credit_hours = hours(item.get("count")), hours(item.get("credits"))
    if rule == Rule.CHOOSE and not (count and count <= len(courses)):
        skipped.append(f"{label}: asks to choose {item.get('count')!r} of {len(courses)} courses")
        return None
    if rule == Rule.CREDITS and not credit_hours:
        skipped.append(f"{label}: credits rule without a number of credit hours")
        return None
    if rule == Rule.CREDITS and None in courses.values():
        skipped.append(f"{label}: kept, but courses without credit hours can't count toward it")

    passage = item.get("passage")
    chunk = batch[passage - 1] if isinstance(passage, int) and 1 <= passage <= len(batch) else None
    return Draft(
        name=name,
        rule=rule,
        required_count=count if rule == Rule.CHOOSE else None,
        credit_hours=credit_hours or None,
        courses=courses,
        source_url=chunk.citation_url[:500] if chunk and source.source_type == DataSource.SourceType.CATALOG_URL else "",
        page_number=chunk.page_number if chunk else None,
    )


def merge(drafts, draft):
    """Add ``draft``, folding it into an earlier one it repeats.

    Overlapping passages can show the same requirement twice, partly each
    time. It is the same requirement when the name and rule match and the
    course lists share a course.
    """
    for earlier in drafts:
        if (
            earlier.name.casefold() == draft.name.casefold()
            and earlier.rule == draft.rule
            and earlier.courses.keys() & draft.courses.keys()
        ):
            for code, credits in draft.courses.items():
                if earlier.courses.get(code) is None:
                    earlier.courses[code] = credits
            earlier.credit_hours = earlier.credit_hours or draft.credit_hours
            return
    drafts.append(draft)


@transaction.atomic
def save(source, thread, drafts):
    """Replace this source's requirements with ``drafts``. Returns the program they belong to."""
    program, _ = DegreeProgram.objects.get_or_create(
        major=source.major, catalog_year=source.catalog_year, thread=thread,
    )
    earlier_programs = set(source.requirement_groups.values_list("program_id", flat=True))
    source.requirement_groups.all().delete()
    for position, draft in enumerate(drafts):
        group = RequirementGroup.objects.create(
            program=program,
            name=draft.name,
            rule=draft.rule,
            required_count=draft.required_count,
            credit_hours=draft.credit_hours,
            position=position,
            source=source,
            source_url=draft.source_url,
            page_number=draft.page_number,
        )
        RequirementCourse.objects.bulk_create(
            RequirementCourse(group=group, code=code, credits=credits) for code, credits in draft.courses.items()
        )
    # A program this source used to fill (e.g. under another thread name) and that is now empty.
    DegreeProgram.objects.filter(pk__in=earlier_programs - {program.pk}, groups__isnull=True).delete()
    return program
