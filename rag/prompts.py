"""US8: choose and assemble the prompt at runtime from the type of question.

Nothing here is a single static prompt. ``classify`` decides the intent of a
question with ordered rules, and ``build_messages`` composes the final prompt
from a shared grounding block, an intent-specific instruction block, and the
retrieved sources. Each intent also tunes retrieval depth and temperature.
"""

import re
from dataclasses import dataclass

NOT_IN_SOURCES = "NOT_IN_SOURCES"


@dataclass(frozen=True)
class Intent:
    key: str
    label: str            # sent to the UI as question_type
    instructions: str     # how to shape the answer
    retrieval_limit: int  # how many chunks to show the model
    temperature: float


INTENTS = {
    "factual_lookup": Intent(
        key="factual_lookup",
        label="Factual lookup",
        instructions=(
            "Give the specific fact first (the number, course, or policy) in one or two "
            "sentences, quoting exact values from the sources. Do not add background."
        ),
        retrieval_limit=4,
        temperature=0.0,
    ),
    "explanation": Intent(
        key="explanation",
        label="Explanation",
        instructions=(
            "Explain the topic in two or three short paragraphs for a student new to it. "
            "Start with the main idea, then the details. Define catalog terms when the "
            "sources define them."
        ),
        retrieval_limit=6,
        temperature=0.2,
    ),
    "comparison": Intent(
        key="comparison",
        label="Comparison",
        instructions=(
            "Describe each option in turn using the same aspects (purpose, required courses, "
            "prerequisites, credit hours) as far as the sources allow, then state the key "
            "differences in one closing sentence. Say clearly if the sources only describe "
            "one of the options."
        ),
        retrieval_limit=8,
        temperature=0.2,
    ),
    "planning": Intent(
        key="planning",
        label="Planning",
        instructions=(
            "List the relevant requirements as a numbered list, note any prerequisites or "
            "sequencing the sources state, and end with one sentence telling the student to "
            "confirm the plan with their academic advisor. Do not assume which courses the "
            "student has completed unless the question says so."
        ),
        retrieval_limit=8,
        temperature=0.2,
    ),
    "general": Intent(
        key="general",
        label="General",
        instructions="Answer in one short paragraph.",
        retrieval_limit=6,
        temperature=0.2,
    ),
}

DEFAULT_INTENT = INTENTS["general"]

# Checked in order; the first match wins. Comparison and planning come before
# factual lookup because "which is harder, CS 1332 or CS 2110?" contains course
# codes but is not a lookup. Each rule records why it matched, for the preview
# endpoint and the sprint demo.
RULES = [
    ("comparison", "asks to compare options",
     re.compile(r"\b(differen(ce|ces|t)|differ|compar(e|ed|ing|ison)|versus|vs\.?|"
                r"which (one |thread |course |option )?is (better|easier|harder|more)|"
                r"between .+ and)\b", re.I)),
    ("planning", "asks what to take or what is still missing",
     re.compile(r"\b((should|can|could|may) i|what (do|should|can) i (take|do)|"
                r"next (semester|term|year)|plan|schedule|still need|remaining|left to|"
                r"have (taken|completed|finished)|on track|graduate on time|"
                r"count (toward|towards)|double[- ]count|in what order)\b", re.I)),
    ("factual_lookup", "asks for a specific number, course, or policy",
     re.compile(r"\b(how (many|much)|credit|credits|hours?|gpa|minimum|maximum|deadline|"
                r"is .+ (required|mandatory|optional)|prereq(uisite)?s?|corequisites?|"
                r"who|when|where|which courses?|what is [a-z]{2,5}\s?\d{4}|"
                r"[a-z]{2,5}\s?\d{4}[a-z]?)\b", re.I)),
    ("explanation", "asks how or why something works",
     re.compile(r"\b(how (do|does|did|is|are)|why|explain|what (is|are|does|do)|describe|"
                r"overview|tell me about|mean(s|ing)?|work(s)?)\b", re.I)),
]


COMPARISON_SPLIT = re.compile(
    r"\bbetween\b|\bversus\b|\bvs\.?\s|\bcompared? (?:to|with)\b|\bcompare\b|\bdifferen(?:ce|ces|t)\b|"
    r"\b(?:and|or)\b|[,?]",
    re.I,
)
COMPARISON_NOISE = re.compile(
    r"^(what|which|how|why|is|are|was|were|does|do|did|can|could|would|will|the|a|an|one|"
    r"harder|easier|better|more|than|of|in|to|for|i|should|take)\b\s*",
    re.I,
)


def comparison_sides(question):
    """The options named in a comparison question, e.g. ["Intelligence", "Systems"].

    Each side is retrieved on its own as well as the whole question, so a chunk
    about one option is not crowded out by chunks that merely repeat the
    question's shared words. Returns [] when fewer than two sides are found.
    """
    sides = []
    for part in COMPARISON_SPLIT.split(question):
        part = (part or "").strip()
        while part:
            cleaned = COMPARISON_NOISE.sub("", part, count=1)
            if cleaned == part:
                break
            part = cleaned
        # Drop a trailing category word ("Intelligence thread" -> "Intelligence"),
        # unless that word is the whole side ("the Threads" -> "Threads").
        trimmed = re.sub(r"\b(thread|threads|course|courses|major|majors|option|options)\b\s*$", "", part, flags=re.I)
        part = (trimmed or part).strip(" ?.")
        if len(part) >= 2 and part.lower() not in {s.lower() for s in sides}:
            sides.append(part)
    return sides if len(sides) >= 2 else []


@dataclass(frozen=True)
class Classification:
    intent: Intent
    rule: str  # human-readable reason, e.g. "asks to compare options"
    matched: str  # the words that triggered the rule, "" for the default


def classify(question):
    """Pick the intent of ``question`` at runtime."""
    for key, reason, pattern in RULES:
        match = pattern.search(question)
        if match:
            return Classification(INTENTS[key], reason, match.group(0))
    return Classification(DEFAULT_INTENT, "no rule matched, default", "")


GROUNDING_RULES = f"""You are DegreeGuide, an assistant for Georgia Tech undergraduates. You answer questions about degree requirements, courses, prerequisites, and graduation progress.

Grounding rules (these override everything else):
1. Use ONLY the numbered sources provided in the user message. Do not use outside knowledge, even if you are confident.
2. Some sources may be unrelated to the question. Ignore those and use only the ones that relate to it.
3. If none of the sources relate to the question, reply with {NOT_IN_SOURCES} followed by one short sentence saying what the sources cover instead and what is missing, without answering from outside knowledge. If related sources answer only part of the question, share what they do say about it and state plainly what they do not cover.
4. After each statement taken from a source, cite it with its number in square brackets, like [1] or [2]. Cite only numbers that exist.
5. Never invent course numbers, credit counts, policies, or deadlines that are not written in the sources.
6. Write plain text. No Markdown, no headings, no tables."""


def system_prompt(intent):
    return f"{GROUNDING_RULES}\n\nThis question is a {intent.label.lower()}. {intent.instructions}"


def context_block(number, chunk, previous=None):
    """Format one retrieved chunk as a numbered source.

    When the chunk directly follows the previous source in the same document
    (a heading-only chunk and the table under it), say so, so the model reads
    them as one passage.
    """
    source = chunk.source
    label = f"[{number}] {source.name} ({source.major}, {source.catalog_year})"
    if chunk.section:
        label += f" - section: {chunk.section}"
    if chunk.page_number:
        label += f" - page {chunk.page_number}"
    if previous is not None and previous.source_id == chunk.source_id and previous.position + 1 == chunk.position:
        label += f" - continues directly from [{number - 1}]"
    return f"{label}\n{chunk.text}"


def build_messages(question, chunks, intent=DEFAULT_INTENT):
    """Return OpenAI-style chat messages for a grounded answer of this intent."""
    context = "\n\n".join(
        context_block(i, chunk, chunks[i - 2] if i > 1 else None) for i, chunk in enumerate(chunks, 1)
    )
    user = (
        f"Sources:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer using only the sources above that relate to the question, citing them like [1]. "
        f"If none of them relate to it, reply with {NOT_IN_SOURCES} and one sentence on what is missing."
    )
    return [
        {"role": "system", "content": system_prompt(intent)},
        {"role": "user", "content": user},
    ]
