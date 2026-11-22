"""Course codes as students type them, turned into one standard form (C1/C2).

"cs1331", "CS-1331" and " cs 1331 " all become "CS 1331". This module has no
model or view imports, so models, forms, the matcher and the extraction
command can all use it.
"""

import re

# A subject of 2-5 letters, an optional space/dash/dot, four digits, and an
# optional letter suffix (e.g. CHEM 1211K).
_CODE = r"([A-Za-z]{2,5})\s*[-_.]?\s*(\d{4}[A-Za-z]?)"
COURSE_CODE = re.compile(rf"^{_CODE}$")
CODE_IN_TEXT = re.compile(rf"(?<![A-Za-z]){_CODE}(?![A-Za-z0-9])")
# Students separate courses with commas, semicolons, or new lines.
SEPARATORS = re.compile(r"[,;\n]+")


def normalize_course_code(text):
    """Return ``text`` as "SUBJ 1234", or None if it isn't one course code."""
    match = COURSE_CODE.match(" ".join(str(text).split()))
    if not match:
        return None
    return f"{match[1].upper()} {match[2].upper()}"


def read_courses(courses):
    """Split what a student entered into course codes and the parts that aren't codes.

    ``courses`` is either one string ("cs1331, CS-1332\\nMATH 1551") or an
    iterable of strings. Codes may also be separated by spaces
    ("CS 1331 CS 1332"). Returns ``(codes, unrecognized)``: normalized codes
    in the order entered without duplicates, and every piece that is not a
    course code, as typed.
    """
    text = courses if isinstance(courses, str) else "\n".join(str(item) for item in courses)
    codes, unrecognized = [], []
    for piece in SEPARATORS.split(text):
        piece = " ".join(piece.split())
        if not piece:
            continue
        found = list(CODE_IN_TEXT.finditer(piece))
        if not found or CODE_IN_TEXT.sub("", piece).strip():
            # Something other than course codes is in this piece.
            if piece not in unrecognized:
                unrecognized.append(piece)
            continue
        for match in found:
            code = f"{match[1].upper()} {match[2].upper()}"
            if code not in codes:
                codes.append(code)
    return codes, unrecognized
