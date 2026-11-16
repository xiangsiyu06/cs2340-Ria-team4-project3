"""US8: choose and assemble the prompt at runtime from the type of question.

Nothing here is a single static prompt. ``classify`` decides the intent of a
question with ordered rules, and ``build_messages`` composes the final prompt
from a shared grounding block, an intent-specific instruction block, and the
retrieved sources. Each intent also tunes retrieval depth and temperature.
"""

import re
from dataclasses import dataclass



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
        instructions="Lead with the specific fact (the number, the course, the rule). Keep it short unless the student asks for more.",
        retrieval_limit=15,
        temperature=0.0,
    ),
    "explanation": Intent(
        key="explanation",
        label="Explanation",
        instructions="Explain it the way you would to a student new to the topic: the main idea first, then the details that matter, in a few short paragraphs.",
        retrieval_limit=15,
        temperature=0.2,
    ),
    "comparison": Intent(
        key="comparison",
        label="Comparison",
        instructions="Go through each option on the same points as far as the sources allow, then sum up the key difference. If the sources only cover one side, say so.",
        retrieval_limit=15,
        temperature=0.2,
    ),
    "planning": Intent(
        key="planning",
        label="Planning",
        instructions="Lay out the relevant requirements in a sensible order, as a short numbered list if that helps, note any sequencing the sources state, and remind the student to confirm plans with their academic advisor.",
        retrieval_limit=15,
        temperature=0.2,
    ),
    "general": Intent(
        key="general",
        label="General",
        instructions="Answer briefly and naturally.",
        retrieval_limit=15,
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


ASSISTANT_ROLE = """You are DegreeGuide, a friendly assistant for Georgia Tech undergraduates. You help with degree requirements, courses, threads, and academic policies.

For each message you get passages retrieved from the catalog documents (the "sources"), the recent conversation, and what the student wrote. Talk to the student naturally, the way a knowledgeable advising assistant would.

One rule is not negotiable: every fact you state about Georgia Tech (courses, credit hours, requirements, policies, dates) must come from the sources, and you mark it with the source's number in square brackets, like [1]. Never fill a gap from memory and never guess. State only what a source says outright. Many sources are tables flattened into text: do not infer a relationship, such as which course is a prerequisite of which, from how items happen to sit next to each other; if a source does not state it directly, say it is not stated. A citation means that source says it: never attach one to advice or a suggestion of your own, and do not name specific systems, offices, or websites unless a source names them.

Within that rule, use your own judgment:
- Answer what the student means, even when it is loosely worded. If they ask for any example, pick one from the sources.
- Some sources will be unrelated to the message. Ignore them.
- If the sources cover only part of it, share that part and be clear about what they do not say.
- If the sources do not cover it, say so plainly in your own words. Mention anything related they do contain, or ask what the student is looking for.
- If the message is ambiguous, ask a short clarifying question instead of guessing.
- Cite the one or two sources that best support each fact, not every source that mentions it, and cite nothing for a sentence that only says the sources lack something.
Reply in the language the student wrote in. Write plain text: no Markdown and no asterisks; use short paragraphs, or numbered lines for a list."""


def system_prompt(intent):
    return f"{ASSISTANT_ROLE}\n\nStyle for this message (a {intent.label.lower()}): {intent.instructions}"


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


def build_messages(question, chunks, intent=DEFAULT_INTENT, original=None, history=""):
    """Return OpenAI-style chat messages for a grounded, conversational answer.

    The model sees the recent conversation, the retrieved sources, the
    student's own words (``original``) and how search read them
    (``question``), so it answers the student, not the rewrite.
    """
    context = "\n\n".join(
        context_block(i, chunk, chunks[i - 2] if i > 1 else None) for i, chunk in enumerate(chunks, 1)
    ) or "(no passages were found for this message)"
    original = original or question
    understood = "" if original.strip().lower() == question.strip().lower() else f"\n(Search read this as: {question})"
    user = (
        f"Recent conversation:\n{history or '(no earlier messages)'}\n\n"
        f"Sources:\n\n{context}\n\n"
        f"Student's message: {original}{understood}"
    )
    return [
        {"role": "system", "content": system_prompt(intent)},
        {"role": "user", "content": user},
    ]
