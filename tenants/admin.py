from django.contrib import admin

from .ingestion import index_source_document
from .models import (
    Company,
    CompanyAIConfig,
    CompanyMembership,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSourceDocument,
    KnowledgeWebSource,
)
from .web_ingestion import index_web_source


class CompanyMembershipInline(admin.TabularInline):
    model = CompanyMembership
    extra = 1
    autocomplete_fields = ('user',)


class CompanyAIConfigInline(admin.StackedInline):
    model = CompanyAIConfig
    can_delete = False


class KnowledgeDocumentInline(admin.TabularInline):
    model = KnowledgeDocument
    extra = 0
    fields = ('title', 'category', 'is_published')


class KnowledgeWebSourceInline(admin.TabularInline):
    model = KnowledgeWebSource
    extra = 1
    fields = (
        'title',
        'url',
        'crawl_mode',
        'crawl_depth',
        'max_pages',
        'refresh_interval',
        'status',
        'next_crawl_at',
        'is_published',
    )
    readonly_fields = ('status', 'next_crawl_at')


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'enable_voice', 'enable_orders', 'created_at')
    list_filter = ('is_active', 'enable_voice', 'enable_orders', 'enable_bookings')
    search_fields = ('name', 'slug', 'contact_email')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [CompanyAIConfigInline, CompanyMembershipInline, KnowledgeDocumentInline, KnowledgeWebSourceInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if isinstance(instance, KnowledgeWebSource) and not instance.created_by_id:
                instance.created_by = request.user
            instance.save()
            if isinstance(instance, KnowledgeWebSource):
                instance.schedule_next_crawl()
                instance.save(update_fields=['next_crawl_at', 'updated_at'])
                index_web_source(instance)
        formset.save_m2m()


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'role', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'company')
    search_fields = ('user__email', 'company__name')
    autocomplete_fields = ('user', 'company')


@admin.register(CompanyAIConfig)
class CompanyAIConfigAdmin(admin.ModelAdmin):
    list_display = ('company', 'text_model', 'realtime_model', 'updated_at')
    search_fields = ('company__name',)


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'category', 'is_published', 'updated_at')
    list_filter = ('company', 'is_published', 'category')
    search_fields = ('title', 'content', 'tags')


@admin.register(KnowledgeSourceDocument)
class KnowledgeSourceDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'file_type', 'status', 'is_published', 'indexed_at')
    list_filter = ('company', 'file_type', 'status', 'is_published')
    search_fields = ('title', 'error_message')
    readonly_fields = ('content_hash', 'status', 'error_message', 'indexed_at', 'created_at', 'updated_at')
    actions = ('reindex_selected',)

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
        index_source_document(obj)

    @admin.action(description='Reindex selected knowledge source documents')
    def reindex_selected(self, request, queryset):
        indexed = 0
        failed = 0
        for source in queryset:
            index_source_document(source)
            source.refresh_from_db(fields=['status'])
            if source.status == KnowledgeSourceDocument.Status.INDEXED:
                indexed += 1
            elif source.status == KnowledgeSourceDocument.Status.FAILED:
                failed += 1
        self.message_user(
            request,
            f'Reindexed {indexed} source document(s); {failed} failed.',
        )


@admin.register(KnowledgeWebSource)
class KnowledgeWebSourceAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'company',
        'url',
        'crawl_mode',
        'refresh_interval',
        'status',
        'last_success_at',
        'next_crawl_at',
        'is_published',
    )
    list_filter = (
        'company',
        'crawl_mode',
        'refresh_interval',
        'status',
        'is_published',
    )
    search_fields = ('title', 'url', 'last_error')
    readonly_fields = (
        'status',
        'content_hash',
        'last_error',
        'last_crawled_at',
        'last_success_at',
        'next_crawl_at',
        'created_at',
        'updated_at',
    )
    actions = ('reindex_selected', 'enable_selected', 'disable_selected')

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        obj.schedule_next_crawl()
        obj.save(update_fields=['next_crawl_at', 'updated_at'])
        index_web_source(obj)

    @admin.action(description='Reindex selected web sources now')
    def reindex_selected(self, request, queryset):
        indexed = 0
        unchanged = 0
        failed = 0
        for source in queryset:
            index_web_source(source)
            source.refresh_from_db(fields=['status'])
            if source.status == KnowledgeWebSource.Status.INDEXED:
                indexed += 1
            elif source.status == KnowledgeWebSource.Status.UNCHANGED:
                unchanged += 1
            elif source.status == KnowledgeWebSource.Status.FAILED:
                failed += 1
        self.message_user(
            request,
            f'Reindexed {indexed}; unchanged {unchanged}; failed {failed}.',
        )

    @admin.action(description='Enable selected web sources')
    def enable_selected(self, request, queryset):
        updated = 0
        for source in queryset:
            source.is_published = True
            source.status = KnowledgeWebSource.Status.PENDING
            source.schedule_next_crawl()
            source.save(update_fields=['is_published', 'status', 'next_crawl_at', 'updated_at'])
            updated += 1
        self.message_user(request, f'Enabled {updated} web source(s).')

    @admin.action(description='Disable selected web sources')
    def disable_selected(self, request, queryset):
        updated = queryset.update(
            is_published=False,
            status=KnowledgeWebSource.Status.DISABLED,
            next_crawl_at=None,
        )
        self.message_user(request, f'Disabled {updated} web source(s).')


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ('company', 'chunk_index', 'source_document', 'legacy_document', 'web_source', 'is_active')
    list_filter = ('company', 'is_active')
    search_fields = ('text', 'heading')
    readonly_fields = ('embedding', 'metadata', 'created_at', 'updated_at')
