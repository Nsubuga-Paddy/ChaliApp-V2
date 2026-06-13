# Generated for company-owned scheduled web knowledge sources.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_knowledgesourcedocument_knowledgechunk_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='KnowledgeWebSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=300)),
                ('url', models.URLField(max_length=1000)),
                ('crawl_mode', models.CharField(choices=[('single_page', 'Single page only'), ('same_domain_limited', 'Same-domain limited crawl')], default='single_page', max_length=30)),
                ('crawl_depth', models.PositiveSmallIntegerField(default=0)),
                ('max_pages', models.PositiveSmallIntegerField(default=1)),
                ('refresh_interval', models.CharField(choices=[('manual', 'Manual only'), ('hourly', 'Hourly'), ('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')], default='daily', max_length=20)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('crawling', 'Crawling'), ('indexed', 'Indexed'), ('unchanged', 'Unchanged'), ('failed', 'Failed'), ('disabled', 'Disabled')], default='pending', max_length=20)),
                ('content_hash', models.CharField(blank=True, max_length=64)),
                ('last_error', models.TextField(blank=True)),
                ('last_crawled_at', models.DateTimeField(blank=True, null=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('next_crawl_at', models.DateTimeField(blank=True, null=True)),
                ('is_published', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='knowledge_web_sources', to='tenants.company')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_knowledge_web_sources', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['company__name', 'url'],
            },
        ),
        migrations.AddField(
            model_name='knowledgechunk',
            name='web_source',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='tenants.knowledgewebsource'),
        ),
        migrations.AddIndex(
            model_name='knowledgewebsource',
            index=models.Index(fields=['company', 'status', 'is_published'], name='tenants_kno_company_ff8691_idx'),
        ),
        migrations.AddIndex(
            model_name='knowledgewebsource',
            index=models.Index(fields=['next_crawl_at', 'status'], name='tenants_kno_next_cr_ad0ad2_idx'),
        ),
        migrations.AddIndex(
            model_name='knowledgewebsource',
            index=models.Index(fields=['company', 'url'], name='tenants_kno_company_f78e52_idx'),
        ),
        migrations.AddConstraint(
            model_name='knowledgewebsource',
            constraint=models.UniqueConstraint(fields=('company', 'url'), name='unique_company_web_source_url'),
        ),
        migrations.AddIndex(
            model_name='knowledgechunk',
            index=models.Index(fields=['web_source', 'is_active'], name='tenants_kno_web_sou_14d988_idx'),
        ),
    ]
