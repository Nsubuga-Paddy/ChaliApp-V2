from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0006_add_document_library_crawl_mode'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='knowledgesourcedocument',
            new_name='tenants_kno_company_364bda_idx',
            old_name='tenants_kno_company_shareable_idx',
        ),
        migrations.AlterField(
            model_name='companyaiconfig',
            name='enabled_tools',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='AI tools enabled for chat and voice. Managed via checkboxes in admin.',
            ),
        ),
        migrations.AlterField(
            model_name='companyaiconfig',
            name='transcription_model',
            field=models.CharField(default='gpt-4o-transcribe', max_length=100),
        ),
    ]
