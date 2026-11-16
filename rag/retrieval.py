"""US3: find the published knowledge chunks most relevant to a question.

Ingestion (US6/US7) already stores a sparse word-count vector on every
``Chunk``, so retrieval is BM25 ranking computed in plain Python. No embedding
model or vector store is needed, which keeps the PythonAnywhere deployment
small and dependency-free.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from knowledge.models import Chunk, DataSource
from knowledge.services import published_chunks, term_vector

TOP_K = 12
# A chunk this short is usually a heading or lead-in ("The following classes
# count toward..."); the content it introduces is in the next chunk.
SHORT_CHUNK_CHARS = 200
# Retrieval casts a wide net and the model judges relevance (it must reply
# NOT_IN_SOURCES when nothing it is shown relates to the question). The floor
# only drops chunks that share almost none of the question's vocabulary.
# Calibrated on catalog pages and degree-sheet PDFs; see the PR description.
RELEVANCE_FLOOR = 0.12

# How many candidates each search contributes before the two rankings are merged.
CANDIDATES = 25
# Words too common across this knowledge base to help when searching inside
# the documents the planner picked.
GENERIC = frozenset(
    "georgia tech gt institute technology student university course degree "
    "program requirement catalog information specific".split()
)

# BM25 constants (standard values).
K1 = 1.5
B = 0.75

# Question words that carry no topical meaning. Keeping them would let a chunk
# win simply because it contains "the" or "what" many times.
STOPWORDS = frozenset(
    """
    a an the and or of to in on for at by with from as into about
    i me my we our you your it its this that these those there here
    is are was were be been being am do does did have has had
    what which who whom whose when where why how
    can could should would will shall may might must
    if then than so not no yes any all some each
    tell explain please need want know
    difference different between versus vs compare comparison
    work works like mean means get take many much find help about
    """.split()
)

# Abbreviations students use that the catalog spells out. The original term
# is kept too, so documents that do use the abbreviation still match.
ABBREVIATIONS = {
    "bs": ("bachelor", "science"),
    "ba": ("bachelor", "art"),
    "ms": ("master", "science"),
    "cs": ("computer", "science"),
    "math": ("mathematic",),
    "prereq": ("prerequisite",),
    "coreq": ("corequisite",),
}

# Course codes such as "cs1332" (ingestion already joins "CS 1332" into one
# term). One mention is a complete match, so they skip BM25's length penalty.
COURSE_CODE = re.compile(r"^[a-z]{2,5}\d{4}[a-z]?$")


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def stem(term):
    """Fold simple plurals so "prerequisites" matches "prerequisite"."""
    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 5 and term.endswith("sses"):
        return term[:-2]
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def stemmed(vector):
    counts = Counter()
    for term, count in vector.items():
        counts[stem(term)] += count
    return counts


def query_terms(question):
    """Stemmed terms of the question, without stopwords, plus expanded abbreviations."""
    terms = set()
    for term in term_vector(question):
        if term in STOPWORDS:
            continue
        term = stem(term)
        terms.add(term)
        terms.update(ABBREVIATIONS.get(term, ()))
    return terms


def with_metadata(vector, *labels):
    """Let a chunk match on its source name, major, and section heading too.

    A requirements table is mostly course codes, so a question like "what does
    the CS degree require" would otherwise never reach it.
    """
    vector = dict(vector)
    for term in term_vector(" ".join(labels)):
        vector[term] = vector.get(term, 0) + 1
    return vector


def retrieve(question, *, limit=TOP_K, floor=RELEVANCE_FLOOR):
    """Return up to ``limit`` hits scoring at least ``floor``, best first.

    Only question words that appear somewhere in the knowledge base count.
    A word no document contains ("BS" when the catalog writes "Bachelor of
    Science") cannot tell chunks apart, so it must not drag every chunk's
    score down. If none of the question's words appear anywhere, there is
    nothing to retrieve and the answer service refuses without calling the
    model.

    Scores are BM25 divided by the best score any chunk could reach for the
    known words, so they fall between 0 and 1 and ``floor`` is comparable
    across questions. Only chunks from active, ready sources take part
    (``published_chunks``), so inactive or half-imported data never reaches
    an answer.
    """
    terms = query_terms(question)
    if not terms:
        return []

    corpus = [
        (chunk_id, stemmed(with_metadata(vector, name, major, section)))
        for chunk_id, vector, name, major, section in published_chunks().values_list(
            "id", "vector", "source__name", "source__major", "section",
        )
    ]
    if not corpus:
        return []

    total = len(corpus)
    document_frequency = Counter()
    for _, vector in corpus:
        document_frequency.update(vector.keys())
    average_length = sum(sum(v.values()) for _, v in corpus) / total

    known = {term for term in terms if document_frequency[term]}
    if not known:
        return []

    def idf(term):
        df = document_frequency[term]
        return math.log(1 + (total - df + 0.5) / (df + 0.5))

    best_possible = sum(idf(t) * (K1 + 1) for t in known)
    scored = []
    for chunk_id, vector in corpus:
        length_norm = K1 * (1 - B + B * sum(vector.values()) / average_length)
        score = 0.0
        for term in known:
            tf = vector.get(term)
            if not tf:
                continue
            if COURSE_CODE.match(term):
                score += idf(term) * (K1 + 1)
            else:
                score += idf(term) * tf * (K1 + 1) / (tf + length_norm)
        score /= best_possible
        if score > 0 and score >= floor:
            scored.append((score, chunk_id))
    scored.sort(reverse=True)
    scored = scored[:limit]

    chunks = Chunk.objects.select_related("source").in_bulk([cid for _, cid in scored])
    return [Hit(chunks[cid], round(score, 4)) for score, cid in scored if cid in chunks]


def with_neighbors(hits):
    """Chunks for the model: each hit, plus the next chunk after a very short one.

    Ingestion splits on headings, so a heading-only section can be retrieved
    without the table or list that follows it. Order is preserved; duplicates
    are dropped.
    """
    chunks = []
    seen = set()
    for hit in hits:
        for chunk in (hit.chunk, next_chunk(hit.chunk)):
            if chunk is not None and chunk.id not in seen:
                seen.add(chunk.id)
                chunks.append(chunk)
    return chunks


def next_chunk(chunk):
    if len(chunk.text) >= SHORT_CHUNK_CHARS:
        return None
    return (
        Chunk.objects.select_related("source")
        .filter(source=chunk.source, position=chunk.position + 1)
        .first()
    )


def document_cards():
    """One line per published document for the planner: (number, source id, text).

    Each line gives the document's name, its file name, and its most
    distinctive terms, so the model can pick documents even when a name is
    vague. Numbers are positions in this list and only valid for one request.
    """
    terms_by_source = {}
    for source_id, vector in published_chunks().values_list("source_id", "vector"):
        terms_by_source.setdefault(source_id, Counter()).update(stemmed(vector))
    document_frequency = Counter()
    for terms in terms_by_source.values():
        document_frequency.update(terms.keys())
    total = len(terms_by_source)
    cards = []
    sources = DataSource.objects.filter(id__in=terms_by_source).order_by("id")
    for number, source in enumerate(sources, 1):
        terms = terms_by_source[source.id]
        size = sum(terms.values()) or 1
        distinctive = sorted(
            terms, key=lambda t: -(terms[t] / size) * math.log(total / document_frequency[t]) if document_frequency[t] < total else 0,
        )[:8]
        label = source.name + (f" (file: {source.file_basename})" if source.file_basename else "")
        cards.append((number, source.id, f"{number}. {label} - key terms: {', '.join(distinctive)}"))
    return cards


def search_inside(source_ids, text, limit=CANDIDATES):
    """Chunk ids ranked by BM25 within the given documents only."""
    corpus = [
        (chunk_id, stemmed(vector))
        for chunk_id, vector in published_chunks().filter(source_id__in=source_ids).values_list("id", "vector")
    ]
    terms = query_terms(text)
    terms = {t for t in terms if t not in GENERIC} or terms
    if not corpus or not terms:
        return []
    total = len(corpus)
    document_frequency = Counter()
    for _, vector in corpus:
        document_frequency.update(vector.keys())
    average_length = sum(sum(v.values()) for _, v in corpus) / total
    known = [t for t in terms if document_frequency[t]]
    idf = {t: math.log(1 + (total - document_frequency[t] + 0.5) / (document_frequency[t] + 0.5)) for t in known}
    scored = []
    for chunk_id, vector in corpus:
        length_norm = K1 * (1 - B + B * sum(vector.values()) / average_length)
        score = 0.0
        for term in known:
            tf = vector.get(term)
            if tf:
                score += idf[term] * (K1 + 1) if COURSE_CODE.match(term) else idf[term] * tf * (K1 + 1) / (tf + length_norm)
        if score > 0:
            scored.append((-score, chunk_id))
    scored.sort()
    return [chunk_id for _, chunk_id in scored[:limit]]


def retrieve_blended(question, *, documents=(), search_terms=(), limit=TOP_K):
    """Merge two rankings: the whole knowledge base, and the planner's documents.

    Searching everything with the question alone is strong for specific
    questions. Searching inside the documents the planner picked is strong
    for broad ones ("what are the CS degree requirements"). Reciprocal rank
    fusion merges the two lists, so a chunk ranked high in either reaches the
    model. With no documents picked this is plain ``retrieve``.
    """
    everywhere = retrieve(question, limit=CANDIDATES)
    if not documents:
        return everywhere[:limit]
    inside = search_inside(documents, " ".join([question, *search_terms]))
    fused = Counter()
    for ranking in ([hit.chunk.id for hit in everywhere], inside):
        for rank, chunk_id in enumerate(ranking, 1):
            fused[chunk_id] += 1 / (60 + rank)
    top = [chunk_id for chunk_id, _ in sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:limit]]
    chunks = Chunk.objects.select_related("source").in_bulk(top)
    return [Hit(chunks[cid], round(fused[cid], 4)) for cid in top if cid in chunks]
