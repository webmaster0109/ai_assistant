import re

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .models import ChatDocumentChunk, ChatSession


CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
MAX_CONTEXT_CHUNKS = 4
WORD_PATTERN = re.compile(r"[a-zA-Z0-9]{3,}")


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


def build_document_context(session_id, question, limit=MAX_CONTEXT_CHUNKS):
    session = ChatSession.objects.filter(id=session_id).prefetch_related("documents__chunks").first()
    if session is None:
        return ""

    document = session.get_active_document()
    if document is None:
        return ""

    chunks = list(document.chunks.all())
    if not chunks:
        return ""

    query_tokens = tokenize_query(question)

    def score(chunk):
        content_lower = chunk.content.lower()
        overlap = sum(content_lower.count(token) for token in query_tokens)
        return overlap, -chunk.chunk_index

    ranked = sorted(chunks, key=score, reverse=True)
    if query_tokens:
        ranked = [chunk for chunk in ranked if score(chunk)[0] > 0] or ranked

    selected = ranked[:limit]
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
