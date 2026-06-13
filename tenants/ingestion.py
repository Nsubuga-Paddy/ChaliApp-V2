import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from openai import OpenAI

from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeSourceDocument

logger = logging.getLogger(__name__)

TARGET_CHUNK_TOKENS = 450
CHUNK_OVERLAP_TOKENS = 80


@dataclass
class ExtractedSection:
    text: str
    heading: str = ''
    page_number: int | None = None
    slide_number: int | None = None


def infer_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip('.')
    if ext in {'pdf', 'docx', 'pptx', 'txt'}:
        return ext
    return ''


def index_source_document(source: KnowledgeSourceDocument) -> KnowledgeSourceDocument:
    source.status = KnowledgeSourceDocument.Status.PROCESSING
    source.error_message = ''
    source.save(update_fields=['status', 'error_message', 'updated_at'])

    try:
        with source.file.open('rb') as handle:
            raw = handle.read()
        content_hash = hashlib.sha256(raw).hexdigest()
        sections = extract_source_sections(source, raw)
        chunks = build_chunks(sections)
        embeddings = embed_texts([chunk['text'] for chunk in chunks])

        with transaction.atomic():
            source.content_hash = content_hash
            source.status = KnowledgeSourceDocument.Status.INDEXED
            source.indexed_at = timezone.now()
            source.error_message = ''
            source.save(
                update_fields=[
                    'content_hash',
                    'status',
                    'indexed_at',
                    'error_message',
                    'updated_at',
                ],
            )
            KnowledgeChunk.objects.filter(source_document=source).delete()
            KnowledgeChunk.objects.bulk_create(
                [
                    KnowledgeChunk(
                        company=source.company,
                        source_document=source,
                        chunk_index=index,
                        text=chunk['text'],
                        heading=chunk.get('heading', ''),
                        page_number=chunk.get('page_number'),
                        slide_number=chunk.get('slide_number'),
                        token_count=chunk['token_count'],
                        embedding=embeddings[index] if index < len(embeddings) else [],
                        metadata={
                            'source_title': source.title,
                            'file_type': source.file_type,
                        },
                    )
                    for index, chunk in enumerate(chunks)
                ]
            )
    except Exception as exc:
        logger.exception('Knowledge source indexing failed: %s', source.pk)
        source.status = KnowledgeSourceDocument.Status.FAILED
        source.error_message = str(exc)
        source.save(update_fields=['status', 'error_message', 'updated_at'])
    return source


def index_legacy_document(document: KnowledgeDocument) -> None:
    sections = [
        ExtractedSection(
            text=document.content,
            heading=document.title,
        )
    ]
    chunks = build_chunks(sections)
    embeddings = embed_texts([chunk['text'] for chunk in chunks])
    with transaction.atomic():
        KnowledgeChunk.objects.filter(legacy_document=document).delete()
        if not document.is_published:
            return
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    company=document.company,
                    legacy_document=document,
                    chunk_index=index,
                    text=chunk['text'],
                    heading=chunk.get('heading', document.title),
                    token_count=chunk['token_count'],
                    embedding=embeddings[index] if index < len(embeddings) else [],
                    metadata={
                        'source_title': document.title,
                        'category': document.category,
                        'tags': document.tag_list,
                        'legacy_document_id': document.id,
                    },
                )
                for index, chunk in enumerate(chunks)
            ]
        )


def extract_source_sections(
    source: KnowledgeSourceDocument,
    raw: bytes,
) -> list[ExtractedSection]:
    if source.file_type == KnowledgeSourceDocument.FileType.TXT:
        return [ExtractedSection(text=raw.decode('utf-8', errors='ignore'), heading=source.title)]
    if source.file_type == KnowledgeSourceDocument.FileType.PDF:
        return extract_pdf_sections(source.file.path)
    if source.file_type == KnowledgeSourceDocument.FileType.DOCX:
        return extract_docx_sections(source.file.path)
    if source.file_type == KnowledgeSourceDocument.FileType.PPTX:
        return extract_pptx_sections(source.file.path)
    raise ValueError(f'Unsupported knowledge source file type: {source.file_type}')


def extract_pdf_sections(path: str) -> list[ExtractedSection]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('PDF extraction requires pypdf. Install project requirements.') from exc

    reader = PdfReader(path)
    sections = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ''
        if text.strip():
            sections.append(ExtractedSection(text=text, page_number=index))
    return sections


def extract_docx_sections(path: str) -> list[ExtractedSection]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError('DOCX extraction requires python-docx. Install project requirements.') from exc

    document = Document(path)
    sections = []
    heading = ''
    buffer = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = (paragraph.style.name or '').lower()
        if 'heading' in style_name:
            if buffer:
                sections.append(ExtractedSection(text='\n'.join(buffer), heading=heading))
                buffer = []
            heading = text
        else:
            buffer.append(text)
    if buffer:
        sections.append(ExtractedSection(text='\n'.join(buffer), heading=heading))
    return sections


def extract_pptx_sections(path: str) -> list[ExtractedSection]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError('PPTX extraction requires python-pptx. Install project requirements.') from exc

    presentation = Presentation(path)
    sections = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        texts = []
        for shape in slide.shapes:
            if hasattr(shape, 'text') and shape.text.strip():
                texts.append(shape.text.strip())
        notes = getattr(slide, 'notes_slide', None)
        if notes and notes.notes_text_frame and notes.notes_text_frame.text.strip():
            texts.append(notes.notes_text_frame.text.strip())
        if texts:
            sections.append(
                ExtractedSection(
                    text='\n'.join(texts),
                    heading=f'Slide {slide_index}',
                    slide_number=slide_index,
                )
            )
    return sections


def build_chunks(sections: list[ExtractedSection]) -> list[dict]:
    chunks = []
    for section in sections:
        normalized = normalize_text(section.text)
        if not normalized:
            continue
        tokens = normalized.split()
        if len(tokens) <= TARGET_CHUNK_TOKENS:
            chunks.append(chunk_payload(section, normalized, len(tokens)))
            continue
        step = max(TARGET_CHUNK_TOKENS - CHUNK_OVERLAP_TOKENS, 1)
        for start in range(0, len(tokens), step):
            window = tokens[start : start + TARGET_CHUNK_TOKENS]
            if not window:
                continue
            chunks.append(chunk_payload(section, ' '.join(window), len(window)))
            if start + TARGET_CHUNK_TOKENS >= len(tokens):
                break
    return chunks


def chunk_payload(section: ExtractedSection, text: str, token_count: int) -> dict:
    return {
        'text': text,
        'heading': section.heading,
        'page_number': section.page_number,
        'slide_number': section.slide_number,
        'token_count': token_count,
    }


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts or not getattr(settings, 'OPENAI_API_KEY', ''):
        return [[] for _ in texts]

    model = getattr(settings, 'OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.embeddings.create(model=model, input=texts)
        by_index = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in by_index]
    except Exception:
        logger.exception('Embedding generation failed; falling back to lexical retrieval.')
        return [[] for _ in texts]
