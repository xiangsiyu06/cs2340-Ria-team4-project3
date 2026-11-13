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
from .prompts import NOT_IN_SOURCES, build_messages, classify, comparison_sides
from .retrieval import retrieve, with_neighbors

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 2000
EXCERPT_LENGTH = 300

NO_RESULT_TEXT = (
    "I couldn't find anything about that in DegreeGuide's catalog data, so I won't guess. "
    "Try asking about a specific degree requirement, course, or prerequisite, "
    "or check the official catalog and your academic advisor."
)


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


def no_result(intent=None):
    return Answer(NO_RESULT_TEXT, [], intent)


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


def retrieve_for(question, intent):
    """Retrieval strategy per intent (US8).

    A comparison also searches for each named option on its own, so both sides
    reach the model even when one is lexically rarer than the other.
    """
    hits = retrieve(question, limit=intent.retrieval_limit)
    if intent.key == "comparison":
        for side in comparison_sides(question):
            hits.extend(retrieve(side, limit=2))
    best = {}
    for hit in hits:
        if hit.chunk.id not in best or hit.score > best[hit.chunk.id].score:
            best[hit.chunk.id] = hit
    return sorted(best.values(), key=lambda hit: hit.score, reverse=True)[: intent.retrieval_limit]


def answer(question) -> Answer:
    """Answer ``question`` from the knowledge base, or say that it cannot.

    Raises ``InvalidQuestion`` for bad input and ``LLMUnavailable`` when the
    model cannot be reached; it never returns a made-up answer.
    """
    question = clean_question(question)
    intent = classify(question).intent
    hits = retrieve_for(question, intent)
    if not hits:
        logger.info("No relevant chunks for %s question: %r", intent.key, question)
        return no_result(intent.label)

    chunks = with_neighbors(hits)
    text = complete(build_messages(question, chunks, intent), temperature=intent.temperature)
    if NOT_IN_SOURCES in text:
        return no_result(intent.label)

    text, used = cited_chunks(text, chunks)
    return Answer(text=text, sources=[source_for(chunk) for chunk in used], intent=intent.label)
