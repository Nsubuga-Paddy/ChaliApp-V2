from django.core.management.base import BaseCommand

from tenants.ingestion import index_legacy_document, index_source_document
from tenants.models import Company, KnowledgeDocument, KnowledgeSourceDocument


class Command(BaseCommand):
    help = 'Rebuild company-scoped knowledge chunks for uploaded and manual knowledge documents.'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=int, help='Limit reindexing to one company id.')
        parser.add_argument(
            '--sources-only',
            action='store_true',
            help='Only reindex uploaded source documents.',
        )
        parser.add_argument(
            '--legacy-only',
            action='store_true',
            help='Only reindex manual KnowledgeDocument rows.',
        )

    def handle(self, *args, **options):
        company_id = options.get('company_id')
        companies = Company.objects.all()
        if company_id:
            companies = companies.filter(pk=company_id)

        source_count = 0
        legacy_count = 0
        for company in companies:
            if not options['legacy_only']:
                for source in KnowledgeSourceDocument.objects.filter(company=company):
                    index_source_document(source)
                    source_count += 1
            if not options['sources_only']:
                for document in KnowledgeDocument.objects.filter(company=company):
                    index_legacy_document(document)
                    legacy_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Reindexed {source_count} source documents and {legacy_count} manual documents.'
            )
        )
