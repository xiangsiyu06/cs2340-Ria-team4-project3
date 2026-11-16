"""US3/US8: answer a student's message using only the published knowledge base.

The assistant works in two steps. First it decides whether it needs to look
anything up (rag/planner.py). If it does, the passages are retrieved here and
a second model call writes the reply from them. The model is given its role,
the conversation, the sources and the student's own words, and one hard rule:
every Georgia Tech fact must come from the sources and be cited. How it
replies beyond that (answering, answering in part, saying it could not find
something, asking what the student means) is its own judgment. The sources
returned are exactly the passages the reply cited.
"""

import logging
import re
from dataclasses import dataclass, field

from .llm import complete
from .planner import conversation_text, plan
from .prompts import INTENTS, build_messages, classify, comparison_sides
from .retrieval import document_cards, retrieve, retrieve_blended, with_neighbors

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 2000
EXCERPT_LENGTH = 300
# The model may read 15 passages; the student is shown at most this many sources.
MAX_SOURCES = 4

# Only used when the model cannot be reached to plan the search and nothing
# is found for the message as typed. Normally the model words its own reply.
NO_RESULT_TEXT = "I couldn't find an answer to"


class InvalidQuestion(ValueError):
    """The question is missing, empty, or too long."""


@dataclass(frozen=True)
class Source:
    title: str
    url: str | None = None
    page: int | None = None
    excerpt: str | None = None

    def as_dict(self):
        return {"title": self.title, "url": self.url, "page": self.page, "excerpt": self.excerpt}


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    intent: str | None = None

    def as_dict(self):
        """The JSON shape agreed in docs/chat-api.md."""
        data = {"answer": self.text, "sources": [s.as_dict() for s in self.sources]}
        if self.intent:
            data["question_type"] = self.intent
        return data


def clean_question(question):
    if not isinstance(question, str):
        raise InvalidQuestion("Send the question as text.")
    question = " ".join(question.split())
    if not question:
        raise InvalidQuestion("Enter a question.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise InvalidQuestion(f"Keep the question under {MAX_QUESTION_LENGTH:,} characters.")
    return question


def no_result(intent=None, question="", reason=""):
    """A natural "couldn't find" reply: what was asked, why it failed, and what is covered."""
    from knowledge.models import DataSource

    topic = question if len(question) <= 120 else question[:117] + "..."
    names = list(dict.fromkeys(
        DataSource.objects.filter(is_active=True, status=DataSource.Status.READY).values_list("name", flat=True)
    ))
    if len(names) > 6:
        covers = f"{len(names)} catalog documents"
    else:
        covers = ", ".join(names) if names else "no sources yet"
    reason = reason.strip() or "None of the passages I have answer it."
    if not reason.endswith((".", "!", "?")):
        reason += "."
    text = (
        f'{NO_RESULT_TEXT} "{topic}" in DegreeGuide\'s catalog data. {reason} '
        f"Right now I can answer from: {covers}. Try naming a specific program, course, or policy, "
        f"or check the official catalog and your academic advisor."
    )
    return Answer(text, [], intent)


def excerpt(text):
    text = " ".join(text.split())
    if len(text) <= EXCERPT_LENGTH:
        return text
    cut = text.rfind(" ", 0, EXCERPT_LENGTH)
    return text[: cut if cut > 0 else EXCERPT_LENGTH] + "…"


def source_for(chunk):
    title = chunk.source.name
    if chunk.section:
        title = f"{title}: {chunk.section}"
    return Source(title=title, url=chunk.citation_url, page=chunk.page_number, excerpt=excerpt(chunk.text))


# One citation group: [2], or a list the model sometimes writes, like [4, 5].
CITATION = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def source_key(chunk):
    """What counts as "the same source" for the student: a PDF page, or a section of a web page."""
    if not hasattr(chunk, "source_id"):
        return chunk
    if chunk.page_number is not None:
        return (chunk.source_id, "page", chunk.page_number)
    return (chunk.source_id, "section", chunk.anchor or chunk.section or chunk.id)


def cited_chunks(text, chunks):
    """Passages referenced as [n] in the reply, as the short list shown to the student.

    The model reads many passages; the student should see a few. Citations to
    the same document and page become one source, at most ``MAX_SOURCES`` are
    kept (in order of first mention), and the numbers in the text are rewritten
    to match that list. Grouped citations such as [4, 5] are handled, unknown
    numbers are dropped, and a reply that cites nothing shows no sources.
    """
    order = {}   # (document, page) -> number shown to the student
    shown = []   # first cited passage for each number

    def renumber(match):
        numbers = []
        for part in re.split(r"\s*[,;]\s*", match.group(1)):
            index = int(part) - 1
            if not 0 <= index < len(chunks):
                continue
            chunk = chunks[index]
            key = source_key(chunk)
            if key not in order:
                if len(order) >= MAX_SOURCES:
                    continue
                order[key] = len(order) + 1
                shown.append(chunk)
            if order[key] not in numbers:
                numbers.append(order[key])
        return "[" + ", ".join(map(str, sorted(numbers))) + "]" if numbers else ""

    text = CITATION.sub(renumber, text)
    text = re.sub(r"[ \t]+(?=[.,;:!?\n])", "", re.sub(r"[ \t]{2,}", " ", text)).strip()
    return text, shown


def retrieve_for(question, intent, planned=None, original=None):
    """Retrieval strategy per intent (US8), using the planner's document picks.

    The base ranking blends a search over everything with a search inside the
    documents the planner chose. A comparison also searches for each named
    option on its own, so both sides reach the model.
    """
    documents = planned.document_ids if planned else ()
    terms = planned.search_terms if planned else ()
    # Search with the student's own words as well as the rewrite, so a rewrite
    # that drifts cannot hide the passages the student was asking about.
    everything = question if not original or original.lower() == question.lower() else f"{question} {original}"
    hits = retrieve_blended(everything, documents=documents, search_terms=terms, limit=intent.retrieval_limit)
    if intent.key == "comparison":
        seen = {hit.chunk.id for hit in hits}
        extra = [hit for side in comparison_sides(question) for hit in retrieve(side, limit=2) if hit.chunk.id not in seen]
        extra = list({hit.chunk.id: hit for hit in extra}.values())
        hits = hits[: max(0, intent.retrieval_limit - len(extra))] + extra
    return hits


def choose_intent(planned):
    """US8: the planner's question type, or the keyword rules when it gave none."""
    return INTENTS.get(planned.intent_key) or classify(planned.question).intent


def answer(question, history=()) -> Answer:
    """Reply to ``question`` from the knowledge base.

    Raises ``InvalidQuestion`` for bad input and ``LLMUnavailable`` when the
    model cannot be reached to write the reply; nothing is ever made up in
    its place.
    """
    original = clean_question(question)
    planned = plan(original, history, document_cards())
    if not planned.search:
        # A greeting, a question about the assistant, or something to clarify:
        # the model answered directly and no catalog facts are involved.
        return Answer(planned.reply, [], "Conversation")

    question = planned.question
    if question != original:
        logger.info("Search read %r as %r", original, question)
    intent = choose_intent(planned)
    hits = retrieve_for(question, intent, planned, original)
    if not hits and not planned.planned:
        # The planner was unreachable and the message as typed matches nothing.
        return no_result(intent.label, original, "None of its key words appear in the sources I have.")

    chunks = with_neighbors(hits)
    messages = build_messages(question, chunks, intent, original, conversation_text(history) if history else "")
    text = complete(messages, temperature=intent.temperature)
    text, used = cited_chunks(text, chunks)
    return Answer(text=text, sources=[source_for(chunk) for chunk in used], intent=intent.label)
