from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0005_knowledgesourcedocument_is_shareable_origin_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='knowledgewebsource',
            name='crawl_mode',
            field=models.CharField(
                choices=[
                    ('single_page', 'Single page only'),
                    ('same_domain_limited', 'Same-domain limited crawl'),
                    ('document_library', 'Document library'),
                ],
                default='single_page',
                max_length=30,
            ),
        ),
    ]
