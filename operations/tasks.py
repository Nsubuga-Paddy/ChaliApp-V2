from celery import shared_task

from .models import CatalogImportJob
from .services.catalog_import import import_catalog


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 2})
def import_catalog_job(self, job_id: int) -> dict:
    job = CatalogImportJob.objects.select_related('company').get(pk=job_id)
    import_catalog(job)
    job.refresh_from_db(fields=['status', 'items_found', 'log', 'updated_at'])
    return {
        'job_id': job.id,
        'status': job.status,
        'items_found': job.items_found,
        'log': job.log,
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
    }
