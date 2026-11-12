"""US3: build the grounded prompt sent to the model."""

NOT_IN_SOURCES = "NOT_IN_SOURCES"

SYSTEM_PROMPT = f"""You are DegreeGuide, an assistant for Georgia Tech undergraduates. You answer questions about degree requirements, courses, prerequisites, and graduation progress.

Grounding rules (these override everything else):
1. Use ONLY the numbered sources provided in the user message. Do not use outside knowledge, even if you are confident.
2. If the sources do not contain the information needed to answer, reply with exactly {NOT_IN_SOURCES} and nothing else.
3. After each statement taken from a source, cite it with its number in square brackets, like [1] or [2]. Cite only numbers that exist.
4. Never invent course numbers, credit counts, policies, or deadlines that are not written in the sources.
5. Write plain text. No Markdown, no headings, no tables."""


def context_block(number, chunk):
    """Format one retrieved chunk as a numbered source."""
    source = chunk.source
    label = f"[{number}] {source.name} ({source.major}, {source.catalog_year})"
    if chunk.section:
        label += f" - section: {chunk.section}"
    if chunk.page_number:
        label += f" - page {chunk.page_number}"
    return f"{label}\n{chunk.text}"


def build_messages(question, chunks):
    """Return OpenAI-style chat messages for a grounded answer."""
    context = "\n\n".join(context_block(i, chunk) for i, chunk in enumerate(chunks, 1))
    user = (
        f"Sources:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer using only the sources above, citing them like [1]. "
        f"If they do not answer the question, reply with exactly {NOT_IN_SOURCES}."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
