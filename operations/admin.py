from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode

from .models import (
    Booking,
    CallSession,
    CompanyMedia,
    Conversation,
    FollowUp,
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
