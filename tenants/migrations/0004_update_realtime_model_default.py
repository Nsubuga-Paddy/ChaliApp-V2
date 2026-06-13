from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_knowledgewebsource_knowledgechunk_web_source'),
    ]

    operations = [
        migrations.AlterField(
            model_name='companyaiconfig',
            name='realtime_model',
            field=models.CharField(default='gpt-realtime-2', max_length=100),
        ),
    ]
