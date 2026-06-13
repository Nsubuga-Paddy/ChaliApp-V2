from celery import shared_task

from .models import KnowledgeWebSource
from .web_ingestion import index_web_source, refresh_due_web_sources


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def index_knowledge_web_source(self, source_id: int) -> dict:
    source = KnowledgeWebSource.objects.select_related('company').get(pk=source_id)
    index_web_source(source)
    source.refresh_from_db(fields=['status', 'last_error', 'last_success_at', 'next_crawl_at'])
    return {
        'source_id': source.id,
        'status': source.status,
        'last_error': source.last_error,
        'last_success_at': source.last_success_at.isoformat() if source.last_success_at else None,
        'next_crawl_at': source.next_crawl_at.isoformat() if source.next_crawl_at else None,
    }


@shared_task
def refresh_due_knowledge_web_sources(limit: int = 50) -> dict:
    return refresh_due_web_sources(limit=limit)
