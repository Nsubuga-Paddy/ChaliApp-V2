from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Company(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)
    website = models.URLField(blank=True)
    contact_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    enable_voice = models.BooleanField(default=True)
    enable_orders = models.BooleanField(default=False)
    enable_bookings = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'companies'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'company'
            slug = base
            counter = 1
            while Company.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class CompanyMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        AGENT = 'agent', 'Agent'
        VIEWER = 'viewer', 'Viewer'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='company_memberships',
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AGENT)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'company')
        ordering = ['company__name']

    def __str__(self):
        return f'{self.user.email} @ {self.company.name} ({self.role})'


class CompanyAIConfig(models.Model):
    class VoiceChoice(models.TextChoices):
        ALLOY = 'alloy', 'Alloy'
        ASH = 'ash', 'Ash'
        BALLAD = 'ballad', 'Ballad'
        CORAL = 'coral', 'Coral'
        ECHO = 'echo', 'Echo'
        SAGE = 'sage', 'Sage'
        SHIMMER = 'shimmer', 'Shimmer'
        VERSE = 'verse', 'Verse'

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='ai_config',
    )
    text_model = models.CharField(max_length=100, default='gpt-4o')
    realtime_model = models.CharField(max_length=100, default='gpt-realtime-2')
    transcription_model = models.CharField(max_length=100, default='whisper-1')
    tts_model = models.CharField(max_length=100, default='gpt-4o-mini-tts')
    tts_voice = models.CharField(
        max_length=20,
        choices=VoiceChoice.choices,
        default=VoiceChoice.CORAL,
    )
    realtime_voice = models.CharField(
        max_length=20,
        choices=VoiceChoice.choices,
        default=VoiceChoice.CORAL,
    )
    system_prompt = models.TextField(
        default=(
            'You are ChaliAssistant, a helpful customer care AI for {company_name}. '
            'Answer accurately using the company knowledge base. Be polite and concise. '
            'If you cannot resolve an issue, offer to create a support ticket or escalate to a human agent.'
        ),
    )
    voice_system_prompt = models.TextField(
        default=(
            'You are ChaliAssistant on a voice call for {company_name}. '
            'Keep responses short and conversational. Use the knowledge base tools when needed.'
        ),
    )
    temperature = models.FloatField(default=0.7)
    max_tokens = models.PositiveIntegerField(default=1024)
    default_language = models.CharField(max_length=10, default='en')
    auto_create_tickets = models.BooleanField(
        default=True,
        help_text='Allow AI to auto-create tickets when escalation is needed.',
    )
    enabled_tools = models.JSONField(
        default=list,
        blank=True,
        help_text='Tool names enabled for this company, e.g. search_knowledge_base, create_ticket.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'AI config: {self.company.name}'

    def get_text_system_prompt(self):
        return self.system_prompt.format(company_name=self.company.name)

    def get_voice_system_prompt(self):
        return self.voice_system_prompt.format(company_name=self.company.name)

    @classmethod
    def default_enabled_tools(cls):
        return ['search_knowledge_base', 'create_ticket', 'lookup_order', 'lookup_booking']

    def save(self, *args, **kwargs):
        if not self.enabled_tools:
            self.enabled_tools = self.default_enabled_tools()
        super().save(*args, **kwargs)


class KnowledgeDocument(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='knowledge_documents',
    )
    title = models.CharField(max_length=300)
    content = models.TextField()
    category = models.CharField(max_length=100, blank=True)
    tags = models.CharField(max_length=500, blank=True, help_text='Comma-separated tags')
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_knowledge_docs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['company', 'is_published']),
        ]

    def __str__(self):
        return f'{self.company.name}: {self.title}'

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]


def knowledge_source_upload_path(instance, filename):
    return f'knowledge/{instance.company_id}/sources/{filename}'


class KnowledgeSourceDocument(models.Model):
    class FileType(models.TextChoices):
        PDF = 'pdf', 'PDF'
        DOCX = 'docx', 'Word Document'
        PPTX = 'pptx', 'PowerPoint'
        TXT = 'txt', 'Plain Text'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        INDEXED = 'indexed', 'Indexed'
        FAILED = 'failed', 'Failed'

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='knowledge_source_documents',
    )
    title = models.CharField(max_length=300)
    file = models.FileField(upload_to=knowledge_source_upload_path)
    file_type = models.CharField(max_length=20, choices=FileType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    content_hash = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_knowledge_sources',
    )
    is_published = models.BooleanField(default=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['company', 'status', 'is_published']),
            models.Index(fields=['company', 'content_hash']),
        ]

    def __str__(self):
        return f'{self.company.name}: {self.title}'


class KnowledgeWebSource(models.Model):
    class CrawlMode(models.TextChoices):
        SINGLE_PAGE = 'single_page', 'Single page only'
        SAME_DOMAIN_LIMITED = 'same_domain_limited', 'Same-domain limited crawl'

    class RefreshInterval(models.TextChoices):
        MANUAL = 'manual', 'Manual only'
        HOURLY = 'hourly', 'Hourly'
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CRAWLING = 'crawling', 'Crawling'
        INDEXED = 'indexed', 'Indexed'
        UNCHANGED = 'unchanged', 'Unchanged'
        FAILED = 'failed', 'Failed'
        DISABLED = 'disabled', 'Disabled'

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='knowledge_web_sources',
    )
    title = models.CharField(max_length=300, blank=True)
    url = models.URLField(max_length=1000)
    crawl_mode = models.CharField(
        max_length=30,
        choices=CrawlMode.choices,
        default=CrawlMode.SINGLE_PAGE,
    )
    crawl_depth = models.PositiveSmallIntegerField(default=0)
    max_pages = models.PositiveSmallIntegerField(default=1)
    refresh_interval = models.CharField(
        max_length=20,
        choices=RefreshInterval.choices,
        default=RefreshInterval.DAILY,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    content_hash = models.CharField(max_length=64, blank=True)
    last_error = models.TextField(blank=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    next_crawl_at = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_knowledge_web_sources',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company__name', 'url']
        indexes = [
            models.Index(fields=['company', 'status', 'is_published']),
            models.Index(fields=['next_crawl_at', 'status']),
            models.Index(fields=['company', 'url']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['company', 'url'], name='unique_company_web_source_url'),
        ]

    def __str__(self):
        return f'{self.company.name}: {self.title or self.url}'

    def refresh_delta(self):
        if self.refresh_interval == self.RefreshInterval.HOURLY:
            return timedelta(hours=1)
        if self.refresh_interval == self.RefreshInterval.DAILY:
            return timedelta(days=1)
        if self.refresh_interval == self.RefreshInterval.WEEKLY:
            return timedelta(weeks=1)
        if self.refresh_interval == self.RefreshInterval.MONTHLY:
            return timedelta(days=30)
        return None

    def schedule_next_crawl(self, from_time=None):
        delta = self.refresh_delta()
        if delta is None:
            self.next_crawl_at = None
        else:
            self.next_crawl_at = (from_time or timezone.now()) + delta


class KnowledgeChunk(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='knowledge_chunks',
    )
    source_document = models.ForeignKey(
        KnowledgeSourceDocument,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='chunks',
    )
    legacy_document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='chunks',
    )
    web_source = models.ForeignKey(
        KnowledgeWebSource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='chunks',
    )
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    heading = models.CharField(max_length=300, blank=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    slide_number = models.PositiveIntegerField(null=True, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['chunk_index']
        indexes = [
            models.Index(fields=['company', 'is_active']),
            models.Index(fields=['source_document', 'is_active']),
            models.Index(fields=['legacy_document', 'is_active']),
            models.Index(fields=['web_source', 'is_active']),
        ]

    def __str__(self):
        source = self.source_document or self.legacy_document or self.web_source
        return f'{self.company.name}: chunk {self.chunk_index} ({source})'
