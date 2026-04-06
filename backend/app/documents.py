import re

from django.db.models import Prefetch

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .models import ChatDocument, ChatDocumentChunk


CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
MAX_CONTEXT_CHUNKS = 6
MAX_SECTION_CHUNKS = 14
MAX_CONTEXT_CHARACTERS = 18000
WORD_PATTERN = re.compile(r"[a-zA-Z]{2,}|\d+")
CHAPTER_REFERENCE_RE = re.compile(r"\bchapter\s+(\d+)\b", re.IGNORECASE)
PAGE_REFERENCE_RE = re.compile(r"\bpage\s+(\d+)\b", re.IGNORECASE)
BROAD_SUMMARY_PATTERNS = (
    re.compile(r"\breview\b", re.IGNORECASE),
    re.compile(r"\bsummar(?:y|ize)\b", re.IGNORECASE),
    re.compile(r"\boverview\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is)?\s+in\b", re.IGNORECASE),
    re.compile(r"\bpdf\s+content\b", re.IGNORECASE),
    re.compile(r"\bbook\s+content\b", re.IGNORECASE),
    re.compile(r"\bentire\s+(?:pdf|book|document)\b", re.IGNORECASE),
    re.compile(r"\bwhole\s+(?:pdf|book|document)\b", re.IGNORECASE),
)


def extract_pdf_chunks(file_path):
    loader = PyPDFLoader(file_path)
    pages = loader.load()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    chunks = []
    for page in pages:
        page_number = (page.metadata or {}).get("page")
        for piece in splitter.split_text(page.page_content or ""):
            content = piece.strip()
            if not content:
                continue
            chunks.append({
                "page_number": (page_number + 1) if isinstance(page_number, int) else None,
                "content": content,
            })
    return chunks


def tokenize_query(text):
    return {token.lower() for token in WORD_PATTERN.findall(text or "")}


def extract_numeric_references(text, pattern):
    return {int(match.group(1)) for match in pattern.finditer(text or "")}


def has_chapter_reference(content, chapter_number):
    chapter_patterns = (
        rf"\bchapter\s+{chapter_number}\b",
        rf"\bchap(?:ter)?\.?\s*{chapter_number}\b",
        rf"\bunit\s+{chapter_number}\b",
        rf"\b{chapter_number}\s*[\.:)\-]\s+[a-z]",
    )
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in chapter_patterns)


def normalize_snippet(content):
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    return " ".join(lines[:3]).strip()


def looks_like_heading_chunk(content):
    snippet = normalize_snippet(content)
    if not snippet or len(snippet) > 160:
        return False

    if re.search(r"\b(chapter|unit|lesson|module|part)\b", snippet, re.IGNORECASE):
        return True

    return bool(re.match(r"^\d+[\.\):\-]\s+[A-Za-z]", snippet))


def collect_neighbor_chunks(chunks, seed_indexes, radius=1, limit=None):
    chunk_map = {chunk.chunk_index: chunk for chunk in chunks}
    expanded = []
    seen = set()

    for seed_index in seed_indexes:
        for neighbor_index in range(seed_index - radius, seed_index + radius + 1):
            neighbor = chunk_map.get(neighbor_index)
            if neighbor is None or neighbor.chunk_index in seen:
                continue
            seen.add(neighbor.chunk_index)
            expanded.append(neighbor)

    expanded.sort(key=lambda item: item.chunk_index)
    return expanded[:limit] if limit else expanded


def collect_chapter_section_chunks(chunks, requested_chapters):
    if not requested_chapters:
        return []

    chapter_anchor_indexes = [
        chunk.chunk_index
        for chunk in chunks
        if any(has_chapter_reference(chunk.content, chapter_number) for chapter_number in requested_chapters)
    ]
    if not chapter_anchor_indexes:
        return []

    heading_indexes = [
        chunk.chunk_index
        for chunk in chunks
        if looks_like_heading_chunk(chunk.content)
    ]
    chunk_map = {chunk.chunk_index: chunk for chunk in chunks}
    collected = []
    seen = set()

    for anchor_index in chapter_anchor_indexes[:2]:
        next_heading_index = next(
            (index for index in heading_indexes if index > anchor_index),
            None,
        )
        stop_index = (
            min(anchor_index + MAX_SECTION_CHUNKS - 1, next_heading_index - 1)
            if next_heading_index is not None
            else anchor_index + MAX_SECTION_CHUNKS - 1
        )
        start_index = max(0, anchor_index - 1)

        for chunk_index in range(start_index, stop_index + 1):
            chunk = chunk_map.get(chunk_index)
            if chunk is None or chunk.chunk_index in seen:
                continue
            seen.add(chunk.chunk_index)
            collected.append(chunk)

    collected.sort(key=lambda item: item.chunk_index)
    return collected


def trim_context_chunks(chunks, max_characters=MAX_CONTEXT_CHARACTERS):
    trimmed = []
    total_characters = 0

    for chunk in chunks:
        chunk_size = len(chunk.content or "")
        if trimmed and total_characters + chunk_size > max_characters:
            break
        trimmed.append(chunk)
        total_characters += chunk_size

    return trimmed


def is_broad_document_query(question):
    text = str(question or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in BROAD_SUMMARY_PATTERNS)


def collect_overview_chunks(chunks):
    if not chunks:
        return []

    heading_chunks = [chunk for chunk in chunks if looks_like_heading_chunk(chunk.content)]
    if heading_chunks:
        selected = []
        seen = set()
        for chunk in heading_chunks:
            if chunk.chunk_index in seen:
                continue
            seen.add(chunk.chunk_index)
            selected.append(chunk)
            if len(selected) >= MAX_CONTEXT_CHUNKS:
                break

        if selected:
            expanded = collect_neighbor_chunks(
                chunks,
                [chunk.chunk_index for chunk in selected],
                radius=1,
            )
            return trim_context_chunks(expanded)

    total_chunks = len(chunks)
    stride = max(1, total_chunks // MAX_CONTEXT_CHUNKS)
    sampled = []
    seen = set()
    for position in range(0, total_chunks, stride):
        chunk = chunks[position]
        if chunk.chunk_index in seen:
            continue
        seen.add(chunk.chunk_index)
        sampled.append(chunk)
        if len(sampled) >= MAX_CONTEXT_CHUNKS:
            break

    return trim_context_chunks(sampled)


def build_document_context(session_id, question, limit=MAX_CONTEXT_CHUNKS):
    document = (
        ChatDocument.objects.filter(session_id=session_id, is_active=True)
        .prefetch_related(
            Prefetch(
                "chunks",
                queryset=ChatDocumentChunk.objects.order_by("chunk_index"),
            )
        )
        .order_by("-uploaded_at")
        .first()
    )
    if document is None:
        return ""

    chunks = list(document.chunks.all())
    if not chunks:
        return ""

    query_tokens = tokenize_query(question)
    requested_chapters = extract_numeric_references(question, CHAPTER_REFERENCE_RE)
    requested_pages = extract_numeric_references(question, PAGE_REFERENCE_RE)
    broad_query = is_broad_document_query(question)

    def score(chunk):
        content_lower = chunk.content.lower()
        overlap = sum(content_lower.count(token) for token in query_tokens)
        chapter_hits = sum(1 for item in requested_chapters if has_chapter_reference(content_lower, item))
        page_hit = 1 if chunk.page_number and chunk.page_number in requested_pages else 0
        exact_phrase = 1 if "chapter" in query_tokens and chapter_hits else 0
        return page_hit, exact_phrase, chapter_hits, overlap, -chunk.chunk_index

    ranked = sorted(chunks, key=score, reverse=True)
    section_chunks = collect_chapter_section_chunks(chunks, requested_chapters)

    if broad_query and not requested_chapters and not requested_pages:
        selected = collect_overview_chunks(chunks)
    elif section_chunks:
        selected = trim_context_chunks(section_chunks)
    else:
        if requested_pages:
            page_ranked = [chunk for chunk in ranked if chunk.page_number in requested_pages]
            if page_ranked:
                ranked = page_ranked
        elif requested_chapters:
            chapter_ranked = [chunk for chunk in ranked if score(chunk)[1] > 0 or score(chunk)[2] > 0]
            if chapter_ranked:
                ranked = chapter_ranked
        elif query_tokens:
            ranked = [chunk for chunk in ranked if score(chunk)[3] > 0] or ranked

        selected = ranked[:limit]
        if selected:
            selected = collect_neighbor_chunks(
                chunks,
                [chunk.chunk_index for chunk in selected],
                radius=1,
            )
            selected = trim_context_chunks(selected)

    if not selected:
        return ""

    sections = []
    for chunk in sorted(selected, key=lambda item: item.chunk_index):
        label = f"Page {chunk.page_number}" if chunk.page_number else f"Chunk {chunk.chunk_index + 1}"
        sections.append(f"[{label}]\n{chunk.content}")
    return "\n\n".join(sections)


def replace_document_chunks(document, chunks):
    document.chunks.all().delete()
    ChatDocumentChunk.objects.bulk_create(
        [
            ChatDocumentChunk(
                document=document,
                chunk_index=index,
                page_number=chunk.get("page_number"),
                content=chunk["content"],
            )
            for index, chunk in enumerate(chunks)
        ]
    )
