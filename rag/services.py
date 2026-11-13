"""US3/US8: answer a question using only the published knowledge base.

Pipeline: validate -> classify (US8) -> retrieve chunks -> build the prompt
for that intent -> model -> post-check. The model never sees a question
without retrieved context, and the sources returned are exactly the chunks
the answer cited.
"""

import logging
import re
from dataclasses import dataclass, field

from .llm import complete
from .planner import SMALL_TALK_TEXT, plan

THANKS_TEXT = "You're welcome! Ask me anything else about your degree requirements or courses."
from .prompts import NOT_IN_SOURCES, build_messages, classify, comparison_sides
from .retrieval import retrieve, with_neighbors

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 2000
GREETING = re.compile(r"^(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b[\s!.,]*\S{0,20}[\s!.]*$", re.I)
EXCERPT_LENGTH = 300

# Every "couldn't find" reply starts with this, then says what and why.
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
    ))[:6]
    covers = ", ".join(names) if names else "no sources yet"
    reason = reason.strip() or "None of the passages I have answer it."
    if not reason.endswith((".", "!", "?")):
        reason += "."
    text = (
        f'{NO_RESULT_TEXT} "{topic}" in DegreeGuide\'s catalog data. {reason} '
        f"Right now I can answer from: {covers}. Try asking about the requirements or courses there, "
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


def cited_chunks(text, chunks):
    """Chunks referenced as [n] in the answer, in order of first mention.

    Citations are renumbered to match the returned source list, so [1] in the
    answer is always the first source shown. Grouped citations such as [4, 5]
    are handled too. Unknown numbers are dropped. If the model cited nothing,
    fall back to the best-matching chunk so every answer shows a source.
    """
    order = {}

    def renumber(match):
        numbers = []
        for part in re.split(r"\s*[,;]\s*", match.group(1)):
            index = int(part) - 1
            if 0 <= index < len(chunks):
                number = order.setdefault(index, len(order) + 1)
                if number not in numbers:
                    numbers.append(number)
        return "[" + ", ".join(map(str, numbers)) + "]" if numbers else ""

    text = CITATION.sub(renumber, text)
    text = re.sub(r"[ \t]+(?=[.,;:!?\n])", "", re.sub(r"[ \t]{2,}", " ", text)).strip()
    used = [chunks[index] for index in order] or chunks[:1]
    return text, used


def retrieve_for(question, intent, search_text=None):
    """Retrieval strategy per intent (US8).

    A comparison also searches for each named option on its own, so both sides
    reach the model even when one is lexically rarer than the other.
    """
    hits = retrieve(search_text or question, limit=intent.retrieval_limit)
    if intent.key == "comparison":
        for side in comparison_sides(question):
            hits.extend(retrieve(side, limit=2))
    best = {}
    for hit in hits:
        if hit.chunk.id not in best or hit.score > best[hit.chunk.id].score:
            best[hit.chunk.id] = hit
    return sorted(best.values(), key=lambda hit: hit.score, reverse=True)[: intent.retrieval_limit]


def answer(question, history=()) -> Answer:
    """Answer ``question`` from the knowledge base, or say that it cannot.

    Raises ``InvalidQuestion`` for bad input and ``LLMUnavailable`` when the
    model cannot be reached; it never returns a made-up answer.
    """
    question = clean_question(question)
    if GREETING.match(question):
        text = THANKS_TEXT if question.lower().startswith("thank") else SMALL_TALK_TEXT
        return Answer(text, [], "Small talk")
    if not history and not retrieve(question, floor=0.0, limit=1):
        # Shares no words with the knowledge base and isn't a follow-up:
        # refuse without spending a model call.
        logger.info("No overlap with the knowledge base: %r", question)
        return no_result(classify(question).intent.label, question, "None of its key words appear in the sources I have.")
    planned = plan(question, history)
    if planned.small_talk:
        return Answer(SMALL_TALK_TEXT, [], "Small talk")
    question = planned.question
    intent = classify(question).intent
    hits = retrieve_for(question, intent, planned.search_text)
    if not hits:
        logger.info("No relevant chunks for %s question: %r", intent.key, question)
        return no_result(intent.label, question, "The closest passages weren't related enough to answer it.")

    chunks = with_neighbors(hits)
    text = complete(build_messages(question, chunks, intent), temperature=intent.temperature)
    if NOT_IN_SOURCES in text:
        # The model may add one sentence on what the sources do cover.
        reason = text.split(NOT_IN_SOURCES, 1)[1].strip(" .:-\n")[:300]
        return no_result(intent.label, question, reason or "I found related passages, but none of them answer it.")

    text, used = cited_chunks(text, chunks)
    return Answer(text=text, sources=[source_for(chunk) for chunk in used], intent=intent.label)
