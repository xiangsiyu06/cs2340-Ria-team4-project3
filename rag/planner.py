"""US3/US8: the assistant's first step: decide whether to look something up, and what.

DegreeGuide may only state facts that come from its documents, so before
answering it makes one cheap model call to decide: can I just reply (a
greeting, a question about myself, a message I need clarified), or do I need
to search? When it searches, the same call rewrites the message into a
standalone question, picks the documents to look in, suggests search terms,
and labels the question type (US8). If the call fails, the student's message
is searched as typed and the keyword rules in prompts.py pick the type.
"""

import json
import logging
import re
from dataclasses import dataclass

from .llm import LLMUnavailable, complete
from .prompts import INTENTS

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """You are DegreeGuide, an assistant that helps Georgia Tech undergraduates with degree requirements, courses, threads, and academic policies. You may only state facts about Georgia Tech that come from the documents in your knowledge base, so your first step is to decide whether you need to look something up.

You are given the numbered list of documents you have, the recent conversation, and the student's new message. Reply with JSON only:
{"search": true, "standalone_question": "...", "documents": [1, 2], "search_terms": ["...", "..."], "question_type": "...", "reply": ""}

- search: true when a good answer needs information from the documents. false when you can respond without them: a greeting or thanks, a question about what you are or what you can do, a message too unclear to act on, or a request that has nothing to do with studying at Georgia Tech.
- reply: only when search is false. Your reply to the student in your own words, friendly and brief: say what you can help with, or ask what they mean. Do not state facts about Georgia Tech courses, requirements, or policies here.
- standalone_question: when search is true. The student's request in English, complete on its own: resolve "it" or "that" from the conversation, fix typos, expand abbreviations. Keep what they are asking for unchanged.
- documents: the numbers of up to 4 documents most likely to hold the answer, best first. For a comparison include one for each side.
- search_terms: 3 to 6 specific words or short phrases likely to appear in the passage that answers the question.
- question_type: one of factual_lookup (a specific fact), explanation (what something is or how it works), comparison (weighing options), planning (what to take or what remains), general (anything else)."""


@dataclass(frozen=True)
class Plan:
    question: str                  # standalone question used for search and the classifier
    search_terms: tuple = ()       # specific terms for the term-only and in-document searches
    document_ids: tuple = ()       # DataSource ids the model picked
    search: bool = True            # False: the model can reply without looking anything up
    reply: str = ""                # its reply in that case
    planned: bool = False          # False when the model call failed and the message is searched as typed
    intent_key: str | None = None  # question type chosen by the model (US8); None means use the keyword rules


def conversation_text(history):
    return "\n".join(
        f"Student: {turn['q']}\nDegreeGuide: {turn['a'][:300]}" for turn in list(history)[-3:]
    ) or "(no earlier messages)"


def plan(question, history=(), cards=()):
    """Decide whether to search for ``question`` and how.

    ``cards`` is ``retrieval.document_cards()``: (number, source id, line).
    """
    documents = "\n".join(line for _, _, line in cards) or "(no documents)"
    messages = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": (
            f"Documents:\n{documents}\n\nRecent conversation:\n{conversation_text(history)}\n\nNew message: {question}"
        )},
    ]
    try:
        text = complete(messages, temperature=0.0, attempts=1, timeout=12)
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
        reply = str(data.get("reply") or "").strip()
        if data.get("search") is False and reply:
            return Plan(question=question, search=False, reply=reply, planned=True)
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
            planned=True,
            intent_key=intent_key if intent_key in INTENTS else None,
        )
    except (LLMUnavailable, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Planner unavailable, searching the message as typed: %s", exc)
        return Plan(question=question)
