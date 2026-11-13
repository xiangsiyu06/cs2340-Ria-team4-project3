"""US3: let the model plan retrieval before answering.

One cheap model call rewrites the student's message into a standalone
question (resolving "it" or "that course" from the recent conversation) and
picks search terms likely to appear in catalog text. Retrieval then runs on
those terms. If the call fails, the original question is used unchanged.
"""

import json
import logging
import re
from dataclasses import dataclass

from .llm import LLMUnavailable, complete

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """You plan catalog searches for DegreeGuide, a Georgia Tech degree-requirements assistant. You never answer questions yourself.

Given the recent conversation and the student's new message, reply with JSON only, in this shape:
{"standalone_question": "...", "search_terms": ["...", "..."], "small_talk": false}

- standalone_question: the new message rewritten so it makes sense on its own. Replace words like "it", "that", or "this course" with what they refer to in the conversation. Keep the student's meaning.
- search_terms: 3 to 8 words or short phrases likely to appear in catalog text that answers the question. Include spelled-out forms (for example "Bachelor of Science" for BS) and course codes like "CS 2340".
- small_talk: true only for greetings, thanks, or chit-chat that needs no catalog information."""

SMALL_TALK_TEXT = (
    "Hi! I'm DegreeGuide. Ask me about Georgia Tech degree requirements, courses, or threads, "
    "and I'll answer from the catalog with sources you can check."
)


@dataclass(frozen=True)
class Plan:
    question: str      # standalone question used for the prompt and the classifier
    search_text: str   # what retrieval searches for
    small_talk: bool = False
    planned: bool = False  # False when the model call failed and the original question is used


def plan(question, history=()):
    """Return a retrieval plan for ``question`` given earlier turns."""
    conversation = "\n".join(
        f"Student: {turn['q']}\nDegreeGuide: {turn['a'][:300]}" for turn in list(history)[-3:]
    ) or "(no earlier messages)"
    messages = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": f"Recent conversation:\n{conversation}\n\nNew message: {question}"},
    ]
    try:
        text = complete(messages, temperature=0.0, attempts=1, timeout=12)
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
        standalone = str(data.get("standalone_question") or question).strip()[:2000]
        terms = [str(term) for term in data.get("search_terms") or [] if str(term).strip()][:8]
        return Plan(
            question=standalone,
            search_text=" ".join([standalone, *terms]),
            small_talk=bool(data.get("small_talk")),
            planned=True,
        )
    except (LLMUnavailable, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Planner unavailable, searching the original question: %s", exc)
        return Plan(question=question, search_text=question)
