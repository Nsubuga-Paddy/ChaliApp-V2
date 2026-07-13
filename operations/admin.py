from django.contrib import admin
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode

from .services.catalog_import import schedule_catalog_import

from .models import (
    Booking,
    Branch,
    CallSession,
    CatalogImportJob,
    CompanyMedia,
    Conversation,
    FollowUp,
    MenuCategory,
    MenuItem,
    Message,
    Order,
    Ticket,
    TicketComment,
)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'company',
        'customer',
        'status',
        'channel',
        'message_count',
        'last_message_at',
        'updated_at',
    )
    list_filter = ('status', 'channel', 'company')
    search_fields = ('customer__email', 'subject')
    readonly_fields = ('transcript_preview', 'messages_link', 'message_count', 'last_message_at')
    fieldsets = (
        (
            'Conversation',
            {
                'fields': (
                    'company',
                    'customer',
                    'subject',
                    'status',
                    'channel',
                    'assigned_to',
                    'message_count',
                    'last_message_at',
                    'messages_link',
                )
            },
        ),
        ('Transcript Preview (latest 30)', {'fields': ('transcript_preview',)}),
    )

    def messages_link(self, obj):
        url = reverse('admin:operations_message_changelist')
        query = urlencode({'conversation__id__exact': obj.id})
        return format_html('<a href="{}?{}">Open full message list</a>', url, query)

    messages_link.short_description = 'Full message history'

    def transcript_preview(self, obj):
        msgs = obj.messages.order_by('-created_at')[:30]
        if not msgs:
            return 'No messages yet.'
        bubbles = format_html_join(
            '',
            (
                '<div style="margin:8px 0;padding:8px 10px;border-radius:8px;'
                'background:{};border:1px solid #ddd;">'
                '<strong>{}</strong> <span style="color:#666;">{}</span><br>{}</div>'
            ),
            (
                (
                    '#e8f5e9' if m.role == Message.Role.CUSTOMER else '#e3f2fd',
                    m.get_role_display(),
                    m.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    (m.text_content or m.audio_transcript or '[media message]')[:800],
                )
                for m in reversed(msgs)
            ),
        )
        return format_html('<div style="max-height:480px;overflow:auto;">{}</div>', bubbles)

    transcript_preview.short_description = 'Transcript'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'role', 'content_type', 'created_at', 'message_preview')
    list_filter = ('role', 'content_type')
    search_fields = ('conversation__id', 'conversation__customer__email', 'text_content', 'audio_transcript')
    autocomplete_fields = ('conversation',)

    def message_preview(self, obj):
        return (obj.text_content or obj.audio_transcript or '')[:120]


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'status', 'started_at', 'duration_seconds')


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'phone', 'is_active', 'updated_at')
    list_filter = ('company', 'is_active')
    search_fields = ('name', 'address', 'phone', 'company__name')
    autocomplete_fields = ('company',)


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'sort_order', 'updated_at')
    list_filter = ('company',)
    search_fields = ('name', 'company__name')
    autocomplete_fields = ('company',)
    ordering = ('company__name', 'sort_order', 'name')


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        'image_preview',
        'name',
        'company',
        'branch',
        'category',
        'price_display',
        'status',
        'is_available',
        'is_featured',
        'needs_review',
        'extraction_confidence',
        'updated_at',
    )
    list_filter = (
        'company',
        'status',
        'needs_review',
        'is_available',
        'is_featured',
        'category',
        'branch',
    )
    search_fields = (
        'name',
        'description',
        'company__name',
        'category__name',
        'branch__name',
        'source_url',
    )
    autocomplete_fields = ('company', 'branch', 'category')
    readonly_fields = ('image_preview_large', 'created_at', 'updated_at')
    actions = (
        'publish_selected',
        'mark_as_draft',
        'archive_selected',
        'mark_available',
        'mark_unavailable',
        'mark_needs_review',
        'clear_review_flag',
    )
    fieldsets = (
        (
            'Catalog Item',
            {
                'fields': (
                    'company',
                    'branch',
                    'category',
                    'name',
                    'description',
                    ('price', 'currency'),
                    ('is_available', 'is_featured'),
                    ('status', 'needs_review'),
                )
            },
        ),
        ('Image', {'fields': ('image', 'image_preview_large', 'source_image_url')}),
        (
            'Import Review',
            {
                'fields': (
                    'source_url',
                    'extraction_confidence',
                    'metadata',
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )

    def image_preview(self, obj):
        if not obj.image:
            return '-'
        return format_html(
            '<img src="{}" alt="" style="height:48px;width:48px;object-fit:cover;border-radius:6px;">',
            obj.image.url,
        )

    image_preview.short_description = 'Image'

    def image_preview_large(self, obj):
        if not obj.image:
            return 'No image uploaded.'
        return format_html(
            '<img src="{}" alt="" style="max-height:240px;max-width:360px;object-fit:contain;">',
            obj.image.url,
        )

    image_preview_large.short_description = 'Preview'

    def price_display(self, obj):
        if obj.price is None:
            return '-'
        return f'{obj.currency} {obj.price:,.0f}'

    price_display.short_description = 'Price'
    price_display.admin_order_field = 'price'

    @admin.action(description='Publish selected items')
    def publish_selected(self, request, queryset):
        updated = queryset.update(status=MenuItem.Status.PUBLISHED, needs_review=False)
        self.message_user(request, f'Published {updated} menu item(s).')

    @admin.action(description='Move selected items back to draft')
    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status=MenuItem.Status.DRAFT, needs_review=True)
        self.message_user(request, f'Moved {updated} menu item(s) to draft.')

    @admin.action(description='Archive selected items')
    def archive_selected(self, request, queryset):
        updated = queryset.update(status=MenuItem.Status.ARCHIVED, is_available=False)
        self.message_user(request, f'Archived {updated} menu item(s).')

    @admin.action(description='Mark selected items available')
    def mark_available(self, request, queryset):
        updated = queryset.update(is_available=True)
        self.message_user(request, f'Marked {updated} menu item(s) available.')

    @admin.action(description='Mark selected items unavailable')
    def mark_unavailable(self, request, queryset):
        updated = queryset.update(is_available=False)
        self.message_user(request, f'Marked {updated} menu item(s) unavailable.')

    @admin.action(description='Flag selected items for review')
    def mark_needs_review(self, request, queryset):
        updated = queryset.update(needs_review=True)
        self.message_user(request, f'Flagged {updated} menu item(s) for review.')

    @admin.action(description='Clear review flag on selected items')
    def clear_review_flag(self, request, queryset):
        updated = queryset.update(needs_review=False)
        self.message_user(request, f'Cleared review flag on {updated} menu item(s).')


@admin.register(CatalogImportJob)
class CatalogImportJobAdmin(admin.ModelAdmin):
    list_display = ('source_url', 'company', 'status', 'render_mode', 'items_found', 'updated_at')
    list_filter = ('company', 'status', 'render_mode')
    search_fields = ('source_url', 'company__name', 'log')
    autocomplete_fields = ('company',)
    readonly_fields = ('screenshot_preview', 'created_at', 'updated_at')
    actions = ('schedule_selected_imports', 'mark_ready_for_review', 'mark_done', 'mark_failed')
    fieldsets = (
        (
            'Import Job',
            {
                'fields': (
                    'company',
                    'source_url',
                    ('status', 'render_mode'),
                    'items_found',
                    'log',
                )
            },
        ),
        ('Rendered Source', {'fields': ('screenshot', 'screenshot_preview', 'raw_html', 'captured_api')}),
        ('Metadata', {'fields': ('metadata', 'created_at', 'updated_at')}),
    )

    def screenshot_preview(self, obj):
        if not obj.screenshot:
            return 'No screenshot captured.'
        return format_html(
            '<img src="{}" alt="" style="max-height:320px;max-width:480px;object-fit:contain;">',
            obj.screenshot.url,
        )

    screenshot_preview.short_description = 'Screenshot preview'

    def save_model(self, request, obj, form, change):
        should_schedule = not change or 'source_url' in form.changed_data or 'render_mode' in form.changed_data
        if should_schedule:
            obj.status = CatalogImportJob.Status.PENDING
            obj.items_found = 0
        super().save_model(request, obj, form, change)
        if should_schedule:
            transaction.on_commit(lambda: schedule_catalog_import(obj))
            self.message_user(request, 'Catalog import queued. Refresh this page in a few minutes.')

    @admin.action(description='Schedule selected imports')
    def schedule_selected_imports(self, request, queryset):
        count = 0
        for job in queryset:
            job.status = CatalogImportJob.Status.PENDING
            job.items_found = 0
            job.save(update_fields=['status', 'items_found', 'updated_at'])
            transaction.on_commit(lambda job=job: schedule_catalog_import(job))
            count += 1
        self.message_user(request, f'Queued {count} catalog import job(s).')

    @admin.action(description='Mark selected imports ready for review')
    def mark_ready_for_review(self, request, queryset):
        updated = queryset.update(status=CatalogImportJob.Status.REVIEW)
        self.message_user(request, f'Marked {updated} import job(s) ready for review.')

    @admin.action(description='Mark selected imports done')
    def mark_done(self, request, queryset):
        updated = queryset.update(status=CatalogImportJob.Status.DONE)
        self.message_user(request, f'Marked {updated} import job(s) done.')

    @admin.action(description='Mark selected imports failed')
    def mark_failed(self, request, queryset):
        updated = queryset.update(status=CatalogImportJob.Status.FAILED)
        self.message_user(request, f'Marked {updated} import job(s) failed.')


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0


class FollowUpInline(admin.TabularInline):
    model = FollowUp
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'title', 'company', 'status', 'priority', 'created_at')
    list_filter = ('company', 'status', 'priority', 'source')
    search_fields = ('ticket_number', 'title', 'customer__email')
    inlines = [TicketCommentInline, FollowUpInline]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'company', 'customer', 'status', 'total_amount', 'created_at')
    list_filter = ('company', 'status')
    search_fields = ('order_number', 'customer__email')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_number', 'company', 'service_name', 'scheduled_at', 'status')
    list_filter = ('company', 'status')
    search_fields = ('booking_number', 'customer__email', 'service_name')


@admin.register(CompanyMedia)
class CompanyMediaAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'is_shareable', 'created_at')
    list_filter = ('company', 'is_shareable')
    search_fields = ('title', 'description')
