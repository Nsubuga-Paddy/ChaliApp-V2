from django.core.management.base import BaseCommand

from tenants.web_ingestion import refresh_due_web_sources


class Command(BaseCommand):
    help = 'Refresh due company knowledge web sources.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **options):
        result = refresh_due_web_sources(limit=options['limit'])
        self.stdout.write(
            self.style.SUCCESS(
                'Processed {processed}; indexed {indexed}; unchanged {unchanged}; failed {failed}.'.format(
                    **result
                )
            )
        )
