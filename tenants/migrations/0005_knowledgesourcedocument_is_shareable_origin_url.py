from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0004_update_realtime_model_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='knowledgesourcedocument',
            name='is_shareable',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When true, AI may attach this file as a downloadable document in customer chat. '
                    'Review all content carefully before enabling — customers will receive the file directly.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='knowledgesourcedocument',
            name='origin_url',
            field=models.URLField(
                blank=True,
                help_text='Automatically set for crawler-ingested files. Records the public URL from which this document was fetched.',
                max_length=2000,
            ),
        ),
        migrations.AddIndex(
            model_name='knowledgesourcedocument',
            index=models.Index(
                fields=['company', 'is_shareable', 'is_published'],
                name='tenants_kno_company_shareable_idx',
            ),
        ),
        migrations.AddConstraint(
            model_name='knowledgesourcedocument',
            constraint=models.UniqueConstraint(
                condition=models.Q(origin_url__gt=''),
                fields=['company', 'origin_url'],
                name='unique_company_origin_url',
            ),
        ),
    ]
