import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Count, Q


def company_media_upload_path(instance, filename):
    return f'companies/{instance.company_id}/media/{filename}'


class CompanyMedia(models.Model):
    """Company-scoped media library for AI responses and customer sharing."""

    company = models.ForeignKey(
        'tenants.Company',
        on_delete=models.CASCADE,
        related_name='media_assets',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to=company_media_upload_path)
    is_shareable = models.BooleanField(
        default=True,
        help_text='When true, AI may include this asset in customer-facing replies.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_company_media',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.company.name}: {self.title}'


class Conversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        CLOSED = 'closed', 'Closed'
        ESCALATED = 'escalated', 'Escalated'

    class Channel(models.TextChoices):
        CHAT = 'chat', 'Chat'
        VOICE = 'voice', 'Voice'
        MIXED = 'mixed', 'Mixed'

    company = models.ForeignKey(
        'tenants.Company',
        on_delete=models.CASCADE,
        related_name='conversations',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations',
    )
    subject = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.CHAT)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_conversations',
    )
    message_count = models.PositiveIntegerField(default=0)
    assistant_message_count = models.PositiveIntegerField(default=0)
    last_message_preview = models.CharField(max_length=240, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['company', 'customer', 'status']),
        ]

    def __str__(self):
        return f'{self.company.name} / {self.customer.email} ({self.status})'

    def refresh_message_summary(self, save=True):
        stats = self.messages.aggregate(
            total=Count('id'),
            assistant_total=Count('id', filter=Q(role=Message.Role.ASSISTANT)),
        )
        last = self.messages.order_by('-created_at').first()
        self.message_count = stats.get('total') or 0
        self.assistant_message_count = stats.get('assistant_total') or 0
        self.last_message_at = last.created_at if last else None
        if last:
            preview = last.text_content or last.audio_transcript or ''
            self.last_message_preview = preview[:240]
        else:
            self.last_message_preview = ''

        if save:
            self.save(
                update_fields=[
                    'message_count',
                    'assistant_message_count',
                    'last_message_preview',
                    'last_message_at',
                ]
            )


class Message(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        ASSISTANT = 'assistant', 'ChaliAssistant'
        STAFF = 'staff', 'Staff'
        SYSTEM = 'system', 'System'

    class ContentType(models.TextChoices):
        TEXT = 'text', 'Text'
        AUDIO = 'audio', 'Audio'
        IMAGE = 'image', 'Image'

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    content_type = models.CharField(max_length=10, choices=ContentType.choices, default=ContentType.TEXT)
    text_content = models.TextField(blank=True)
    audio_file = models.FileField(upload_to='message_audio/', blank=True, null=True)
    audio_transcript = models.TextField(blank=True)
    image_file = models.ImageField(upload_to='message_images/', blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        preview = (self.text_content or self.audio_transcript or '')[:50]
        return f'{self.role}: {preview}'


class CallSession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='call_sessions',
    )
    openai_session_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    transcript = models.JSONField(default=list, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'Call {self.id} ({self.status})'


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_PROGRESS = 'in_progress', 'In Progress'
        PENDING = 'pending', 'Pending'
        RESOLVED = 'resolved', 'Resolved'
        CLOSED = 'closed', 'Closed'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        URGENT = 'urgent', 'Urgent'

    class Source(models.TextChoices):
        AI_AUTO = 'ai_auto', 'AI Auto'
        STAFF = 'staff', 'Staff'
        CUSTOMER = 'customer', 'Customer'

    company = models.ForeignKey(
        'tenants.Company',
        on_delete=models.CASCADE,
        related_name='tickets',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tickets',
    )
    ticket_number = models.CharField(max_length=30, unique=True, editable=False)
    title = models.CharField(max_length=300)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    category = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.STAFF)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tickets',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['ticket_number']),
        ]

    def __str__(self):
        return f'{self.ticket_number}: {self.title}'

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            self.ticket_number = f'TKT-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class FollowUp(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='follow_ups')
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='follow_ups',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['due_date', '-created_at']


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        PROCESSING = 'processing', 'Processing'
        SHIPPED = 'shipped', 'Shipped'
        DELIVERED = 'delivered', 'Delivered'
        CANCELLED = 'cancelled', 'Cancelled'

    company = models.ForeignKey(
        'tenants.Company',
        on_delete=models.CASCADE,
        related_name='orders',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    order_number = models.CharField(max_length=30, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    items = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['company', 'status'])]

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f'ORD-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        NO_SHOW = 'no_show', 'No Show'

    company = models.ForeignKey(
        'tenants.Company',
        on_delete=models.CASCADE,
        related_name='bookings',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bookings',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
    )
    booking_number = models.CharField(max_length=30, unique=True, editable=False)
    service_name = models.CharField(max_length=200)
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_at']
        indexes = [models.Index(fields=['company', 'status', 'scheduled_at'])]

    def save(self, *args, **kwargs):
        if not self.booking_number:
            self.booking_number = f'BKG-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.booking_number
