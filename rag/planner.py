"""US3/US8: let the model plan retrieval and pick the question type before answering.

One cheap model call rewrites the student's message into a standalone
question (resolving "it" or "that course" from the recent conversation),
picks which documents in the knowledge base to search, and suggests specific
search terms. The same call labels the question type (US8), which decides
the prompt instructions. If the call fails, the original question is
searched across everything and the keyword rules in prompts.py pick the type.
"""

import json
import logging
import re
from dataclasses import dataclass

from .llm import LLMUnavailable, complete
from .prompts import INTENTS

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """You plan catalog searches for DegreeGuide, a Georgia Tech degree-requirements assistant. You never answer questions yourself.

Given the recent conversation, the student's new message, and the numbered list of documents in the knowledge base, reply with JSON only, in this shape:
{"standalone_question": "...", "documents": [1, 2], "search_terms": ["...", "..."], "question_type": "...", "small_talk": false, "off_topic": false}

- standalone_question: the new message rewritten in English so it makes sense on its own. Replace words like "it", "that", or "this course" with what they refer to in the conversation. Fix typos and expand abbreviations (BS = Bachelor of Science, ME = Mechanical Engineering, prereq = prerequisite, hrs = credit hours). Keep the student's meaning.
- documents: the numbers of the 1 to 4 documents most likely to contain the answer, best first. Prefer the document about the specific program, thread, course subject, or policy the question names. For a comparison, include a document for each side. Use an empty list only when no document could help.
- search_terms: 3 to 6 specific words or short phrases likely to appear in the passage that answers the question (course codes, program names, policy words). No generic words such as Georgia Tech, degree, course, student.
- question_type: exactly one of
  "factual_lookup" (asks for a specific fact: a number, a course, whether something is required, a prerequisite),
  "explanation" (asks what something is, how it works, or why; includes "tell me about X"),
  "comparison" (weighs two or more options against each other, including "should I pick A or B"),
  "planning" (asks what to take, in what order, what still counts or remains for the student),
  "general" (anything else).
- small_talk: true only for greetings or thanks.
- off_topic: true when the message is not about Georgia Tech academics at all."""

SMALL_TALK_TEXT = (
    "Hi! I'm DegreeGuide. Ask me about Georgia Tech degree requirements, courses, or threads, "
    "and I'll answer from the catalog with sources you can check."
)


@dataclass(frozen=True)
class Plan:
    question: str                 # standalone question used for the prompt, the global search and the classifier
    search_terms: tuple = ()      # specific terms for searching inside the picked documents
    document_ids: tuple = ()      # DataSource ids the model picked
    small_talk: bool = False
    off_topic: bool = False
    planned: bool = False         # False when the model call failed and the original question is used
    intent_key: str | None = None  # question type chosen by the model (US8); None means use the keyword rules

    @property
    def search_text(self):
        return " ".join([self.question, *self.search_terms])


def plan(question, history=(), cards=()):
    """Return a retrieval plan for ``question`` given earlier turns.

    ``cards`` is ``retrieval.document_cards()``: (number, source id, line).
    """
    conversation = "\n".join(
        f"Student: {turn['q']}\nDegreeGuide: {turn['a'][:300]}" for turn in list(history)[-3:]
    ) or "(no earlier messages)"
    documents = "\n".join(line for _, _, line in cards) or "(no documents)"
    messages = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": f"Documents:\n{documents}\n\nRecent conversation:\n{conversation}\n\nNew message: {question}"},
    ]
    try:
        text = complete(messages, temperature=0.0, attempts=1, timeout=12)
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
        standalone = str(data.get("standalone_question") or question).strip()[:2000]
        terms = tuple(str(term) for term in data.get("search_terms") or [] if str(term).strip())[:6]
        by_number = {number: source_id for number, source_id, _ in cards}
        picked = tuple(dict.fromkeys(
            by_number[n] for n in data.get("documents") or [] if isinstance(n, int) and n in by_number
        ))[:4]
        intent_key = str(data.get("question_type") or "").strip()
        return Plan(
            question=standalone,
            search_terms=terms,
            document_ids=picked,
            small_talk=bool(data.get("small_talk")),
            off_topic=bool(data.get("off_topic")),
            planned=True,
            intent_key=intent_key if intent_key in INTENTS else None,
        )
    except (LLMUnavailable, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Planner unavailable, searching the original question: %s", exc)
        return Plan(question=question)
