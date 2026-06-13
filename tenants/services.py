import hashlib
import math
import re

from django.core.cache import cache
from django.db.models import Q

from .ingestion import embed_texts
from .models import KnowledgeChunk, KnowledgeDocument


def search_knowledge_base(
    company,
    query,
    limit=5,
    max_content_chars=None,
    candidate_limit=500,
):
    if not query or not query.strip():
        return []

    chunk_results = search_knowledge_chunks(
        company,
        query,
        limit=limit,
        max_content_chars=max_content_chars,
        candidate_limit=candidate_limit,
    )
    if chunk_results:
        return chunk_results

    return search_legacy_documents(
        company,
        query,
        limit=limit,
        max_content_chars=max_content_chars,
    )


def search_knowledge_base_for_voice(company, query):
    return search_knowledge_base(
        company,
        query,
        limit=3,
        max_content_chars=900,
        candidate_limit=180,
    )


def search_knowledge_chunks(
    company,
    query,
    limit=5,
    min_score=0.08,
    max_content_chars=None,
    candidate_limit=500,
):
    terms = tokenize(query)
    query_embedding = first_embedding(query, company_id=company.id)
    base_qs = (
        KnowledgeChunk.objects.filter(company=company, is_active=True)
        .filter(
            Q(source_document__isnull=False, source_document__is_published=True)
            | Q(legacy_document__isnull=False, legacy_document__is_published=True)
            | Q(web_source__isnull=False, web_source__is_published=True)
        )
        .select_related('source_document', 'legacy_document', 'web_source')
        .order_by('-updated_at')
    )

    chunks = candidate_chunks(base_qs, terms, candidate_limit)
    scored = []
    for chunk in chunks:
        lexical = lexical_score(chunk, terms)
        vector = cosine_similarity(query_embedding, chunk.embedding)
        score = (0.55 * vector) + (0.45 * lexical)
        if score <= 0:
            continue
        scored.append((score, vector, lexical, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < min_score:
        return []

    results = []
    for score, vector, lexical, chunk in scored[:limit]:
        source = chunk.source_document or chunk.legacy_document or chunk.web_source
        if chunk.web_source_id:
            source_type = 'web'
        elif chunk.source_document_id:
            source_type = 'file'
        else:
            source_type = 'manual'
        results.append(
            {
                'id': chunk.id,
                'title': source.title if source else chunk.heading,
                'category': getattr(source, 'category', '') or chunk.metadata.get('category', ''),
                'content': truncate_content(chunk.text, max_content_chars),
                'score': round(score, 4),
                'confidence': confidence_label(score),
                'source_type': source_type,
                'source_id': source.id if source else None,
                'heading': chunk.heading,
                'page_number': chunk.page_number,
                'slide_number': chunk.slide_number,
                'metadata': {
                    **(chunk.metadata or {}),
                    'vector_score': round(vector, 4),
                    'lexical_score': round(lexical, 4),
                },
            }
        )
    return results


def search_legacy_documents(company, query, limit=5, max_content_chars=None):
    terms = query.strip().split()
    qs = KnowledgeDocument.objects.filter(company=company, is_published=True)

    combined = Q()
    for term in terms:
        combined |= (
            Q(title__icontains=term)
            | Q(content__icontains=term)
            | Q(tags__icontains=term)
            | Q(category__icontains=term)
        )

    docs = qs.filter(combined).order_by('-updated_at')[:limit]
    return [
        {
            'id': doc.id,
            'title': doc.title,
            'category': doc.category,
            'content': truncate_content(doc.content, max_content_chars or 2000),
        }
        for doc in docs
    ]


def candidate_chunks(base_qs, terms, candidate_limit):
    candidate_limit = max(int(candidate_limit or 500), 1)
    if not terms:
        return list(base_qs[:candidate_limit])

    combined = Q()
    for term in terms[:8]:
        combined |= (
            Q(text__icontains=term)
            | Q(heading__icontains=term)
            | Q(metadata__source_title__icontains=term)
            | Q(metadata__category__icontains=term)
        )

    lexical_matches = list(base_qs.filter(combined)[:candidate_limit])
    if len(lexical_matches) >= candidate_limit:
        return lexical_matches

    seen = {chunk.id for chunk in lexical_matches}
    fallback_needed = candidate_limit - len(lexical_matches)
    fallback = [
        chunk
        for chunk in base_qs[: candidate_limit + fallback_needed]
        if chunk.id not in seen
    ][:fallback_needed]
    return lexical_matches + fallback


def tokenize(text):
    return [term for term in re.findall(r'\w+', (text or '').lower()) if len(term) > 1]


def first_embedding(query, company_id=None):
    cache_key = embedding_cache_key(company_id, query)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    embeddings = embed_texts([query])
    embedding = embeddings[0] if embeddings else []
    if embedding:
        cache.set(cache_key, embedding, timeout=60 * 30)
    return embedding


def embedding_cache_key(company_id, query):
    normalized = ' '.join((query or '').lower().split())
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return f'kb-query-embedding:{company_id or "global"}:{digest}'


def truncate_content(content, max_chars):
    if not max_chars or not content or len(content) <= max_chars:
        return content
    return content[:max_chars].rsplit(' ', 1)[0].strip() + '...'


def lexical_score(chunk, terms):
    if not terms:
        return 0.0
    text = ' '.join(
        [
            chunk.text or '',
            chunk.heading or '',
            str(chunk.metadata.get('source_title', '')),
            str(chunk.metadata.get('category', '')),
            ' '.join(chunk.metadata.get('tags', []))
            if isinstance(chunk.metadata.get('tags'), list)
            else str(chunk.metadata.get('tags', '')),
        ]
    ).lower()
    matches = sum(1 for term in terms if term in text)
    density = matches / max(len(set(terms)), 1)
    return min(density, 1.0)


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def confidence_label(score):
    if score >= 0.55:
        return 'high'
    if score >= 0.25:
        return 'medium'
    return 'low'


def format_kb_context(results):
    if not results:
        return 'No relevant knowledge base articles found.'
    parts = []
    for item in results:
        source_bits = []
        if item.get('heading'):
            source_bits.append(item['heading'])
        if item.get('page_number'):
            source_bits.append(f"page {item['page_number']}")
        if item.get('slide_number'):
            source_bits.append(f"slide {item['slide_number']}")
        source = f" - {'; '.join(source_bits)}" if source_bits else ''
        confidence = item.get('confidence', 'unknown')
        parts.append(
            f"### {item['title']} ({item.get('category', '')}){source}\n"
            f"Confidence: {confidence}\n"
            f"{item['content']}"
        )
    return '\n\n'.join(parts)
