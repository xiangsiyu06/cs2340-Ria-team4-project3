"""Normalize extracted text and split it without losing source boundaries."""

import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Section:
    text: str
    heading: str = ""
    page_number: int | None = None
    anchor: str = ""


def clean_text(text):
    lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def prepare_chunks(sections, *, limit=1600, overlap=180):
    if not 0 <= overlap < limit:
        raise ValueError("Chunk overlap must be smaller than the chunk limit.")
    chunks = []
    for section in sections:
        text = clean_text(section.text)
        while len(text) > limit:
            boundary = text.rfind("\n", limit // 2, limit + 1)
            line_boundary = boundary > 0
            if not line_boundary:
                boundary = text.rfind(" ", limit // 2, limit + 1)
            end = boundary if boundary > 0 else limit
            chunks.append(replace(section, text=text[:end].rstrip()))
            start = end
            if overlap:
                # Restart at a word boundary within the overlap, when possible.
                if line_boundary:
                    previous_line = text.find("\n", max(0, end - overlap), end)
                    if previous_line >= 0:
                        start = previous_line + 1
                else:
                    start = next(
                        (i + 1 for i in range(max(0, end - overlap), end) if text[i].isspace()),
                        end,
                    )
            text = text[start:].lstrip()
        if text:
            chunks.append(replace(section, text=text))
    return chunks


def split_pdf_columns(lines):
    """Split pages with a clear central gutter and substantial text on both sides."""
    width = max(map(len, lines), default=0)
    candidates = sorted(range(width * 2 // 5, width * 3 // 5), key=lambda x: abs(x - width / 2))
    for column in candidates:
        if any(line[column:column + 1].strip() for line in lines):
            continue
        paired_rows = sum(
            not line[column - 1:column + 2].strip()
            and len(line[:column].strip()) >= 12
            and len(line[column:].strip()) >= 12
            for line in lines
        )
        left_courses = sum(bool(re.search(r"\b[A-Z]{2,5}\s*\d{4}", line[:column])) for line in lines)
        right_courses = sum(bool(re.search(r"\b[A-Z]{2,5}\s*\d{4}", line[column:])) for line in lines)
        if paired_rows >= max(6, len(lines) // 4) and min(left_courses, right_courses) >= 3:
            return [
                [line[:column].strip() for line in lines if line[:column].strip()],
                [line[column:].strip() for line in lines if line[column:].strip()],
            ]
    return [lines]
