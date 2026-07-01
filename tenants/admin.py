from django.contrib import admin, messages

from .forms import CompanyAIConfigAdminForm, CompanyAIConfigInlineFormSet
from .ingestion import schedule_index_source_document
from .models import (
    Company,
    CompanyAIConfig,
    CompanyMembership,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSourceDocument,
    KnowledgeWebSource,
)
from .web_ingestion import schedule_index_web_source


class CompanyMembershipInline(admin.TabularInline):
    model = CompanyMembership
    extra = 1
    autocomplete_fields = ('user',)


class CompanyAIConfigInline(admin.StackedInline):
    model = CompanyAIConfig
    form = CompanyAIConfigAdminForm
    formset = CompanyAIConfigInlineFormSet
    can_delete = False
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'text_model',
                    'realtime_model',
                    'transcription_model',
                    'tts_model',
                    'tts_voice',
                    'realtime_voice',
                    'enabled_tools_selection',
                    'auto_create_tickets',
                    'temperature',
                    'max_tokens',
                    'default_language',
                ),
            },
        ),
        (
            'Prompts',
            {
                'classes': ('collapse',),
                'fields': ('system_prompt', 'voice_system_prompt'),
            },
        ),
    )


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

    def get_inlines(self, request, obj):
        inlines = super().get_inlines(request, obj)
        if obj is None:
            return [inline for inline in inlines if inline is not CompanyAIConfigInline]
        return inlines

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if isinstance(instance, KnowledgeWebSource) and not instance.created_by_id:
                instance.created_by = request.user
            instance.save()
            if isinstance(instance, KnowledgeWebSource):
                schedule_index_web_source(instance)
        formset.save_m2m()


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'role', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'company')
    search_fields = ('user__email', 'company__name')
    autocomplete_fields = ('user', 'company')


@admin.register(CompanyAIConfig)
class CompanyAIConfigAdmin(admin.ModelAdmin):
    form = CompanyAIConfigAdminForm
    list_display = ('company', 'text_model', 'realtime_model', 'updated_at')
    search_fields = ('company__name',)
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'company',
                    'text_model',
                    'realtime_model',
                    'transcription_model',
                    'tts_model',
                    'tts_voice',
                    'realtime_voice',
                    'enabled_tools_selection',
                    'auto_create_tickets',
                    'temperature',
                    'max_tokens',
                    'default_language',
                ),
            },
        ),
        (
            'Prompts',
            {
                'fields': ('system_prompt', 'voice_system_prompt'),
            },
        ),
    )


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'category', 'is_published', 'updated_at')
    list_filter = ('company', 'is_published', 'category')
    search_fields = ('title', 'content', 'tags')


@admin.register(KnowledgeSourceDocument)
class KnowledgeSourceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'company',
        'file_type',
        'status',
        'is_published',
        'is_shareable',
        'origin_source',
        'indexed_at',
    )
    list_filter = ('company', 'file_type', 'status', 'is_published', 'is_shareable')
    search_fields = ('title', 'origin_url', 'error_message')
    readonly_fields = (
        'content_hash',
        'status',
        'error_message',
        'origin_url',
        'indexed_at',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'company',
                    'title',
                    'file',
                    'file_type',
                    'is_published',
                ),
            },
        ),
        (
            'Sharing',
            {
                'description': (
                    'Mark "Shareable in chat" only after reviewing the document content. '
                    'Customers will receive this exact file as a downloadable attachment.'
                ),
                'fields': ('is_shareable',),
            },
        ),
        (
            'Status & provenance',
            {
                'classes': ('collapse',),
                'fields': (
                    'status',
                    'error_message',
                    'content_hash',
                    'origin_url',
                    'uploaded_by',
                    'indexed_at',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )
    actions = ('reindex_selected', 'mark_shareable', 'mark_not_shareable')

    @admin.display(description='Source')
    def origin_source(self, obj):
        return 'Crawled' if obj.origin_url else 'Uploaded'

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id and not obj.origin_url:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
        schedule_index_source_document(obj)
        self.message_user(
            request,
            'Indexing queued in the background. Refresh this page in a minute to '
            'check status (Processing → Indexed). Large scanned PDFs can take several minutes.',
            messages.SUCCESS,
        )

    @admin.action(description='Reindex selected knowledge source documents')
    def reindex_selected(self, request, queryset):
        queued = 0
        for source in queryset:
            schedule_index_source_document(source)
            queued += 1
        self.message_user(
            request,
            f'Queued {queued} document(s) for background indexing.',
            messages.SUCCESS,
        )

    @admin.action(description='Mark selected documents as shareable in chat')
    def mark_shareable(self, request, queryset):
        updated = queryset.filter(
            status=KnowledgeSourceDocument.Status.INDEXED,
        ).update(is_shareable=True)
        skipped = queryset.count() - updated
        msg = f'Marked {updated} document(s) as shareable.'
        if skipped:
            msg += f' {skipped} skipped (only indexed documents can be shared).'
        self.message_user(request, msg)

    @admin.action(description='Remove shareable flag from selected documents')
    def mark_not_shareable(self, request, queryset):
        updated = queryset.update(is_shareable=False)
        self.message_user(request, f'Removed shareable flag from {updated} document(s).')


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
        schedule_index_web_source(obj)
        self.message_user(
            request,
            'Web source indexing queued in the background. Refresh this page later to check status.',
            messages.SUCCESS,
        )

    @admin.action(description='Queue selected web sources for reindexing')
    def reindex_selected(self, request, queryset):
        queued = 0
        for source in queryset:
            schedule_index_web_source(source)
            queued += 1
        self.message_user(
            request,
            f'Queued {queued} web source(s) for background indexing.',
            messages.SUCCESS,
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
