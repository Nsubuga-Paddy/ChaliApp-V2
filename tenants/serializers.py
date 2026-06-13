from rest_framework import serializers

from .ingestion import infer_file_type
from .models import (
    Company,
    CompanyAIConfig,
    CompanyMembership,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSourceDocument,
    KnowledgeWebSource,
)


def absolute_media_url(serializer, file_field):
    if not file_field:
        return None
    request = serializer.context.get('request')
    if request:
        return request.build_absolute_uri(file_field.url)
    return file_field.url


class CompanyListSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            'id',
            'name',
            'slug',
            'description',
            'logo',
            'website',
            'enable_voice',
            'enable_orders',
            'enable_bookings',
        )

    def get_logo(self, obj):
        return absolute_media_url(self, obj.logo)


class CompanyDetailSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            'id',
            'name',
            'slug',
            'description',
            'logo',
            'website',
            'contact_email',
            'enable_voice',
            'enable_orders',
            'enable_bookings',
            'created_at',
            'updated_at',
        )

    def get_logo(self, obj):
        return absolute_media_url(self, obj.logo)


class CompanyAIConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyAIConfig
        fields = (
            'text_model',
            'realtime_model',
            'transcription_model',
            'tts_model',
            'tts_voice',
            'realtime_voice',
            'system_prompt',
            'voice_system_prompt',
            'temperature',
            'max_tokens',
            'default_language',
            'auto_create_tickets',
            'enabled_tools',
            'updated_at',
        )
        read_only_fields = ('updated_at',)


class CompanyStaffSerializer(serializers.ModelSerializer):
    ai_config = CompanyAIConfigSerializer(read_only=True)
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            'id',
            'name',
            'slug',
            'description',
            'logo',
            'website',
            'contact_email',
            'is_active',
            'enable_voice',
            'enable_orders',
            'enable_bookings',
            'ai_config',
            'created_at',
            'updated_at',
        )

    def get_logo(self, obj):
        return absolute_media_url(self, obj.logo)


class CompanyCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = (
            'name',
            'slug',
            'description',
            'logo',
            'website',
            'contact_email',
            'is_active',
            'enable_voice',
            'enable_orders',
            'enable_bookings',
        )


class CompanyMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = CompanyMembership
        fields = (
            'id',
            'user',
            'user_email',
            'user_name',
            'company',
            'role',
            'is_active',
            'joined_at',
        )
        read_only_fields = ('joined_at',)

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class StaffCompanyMembershipSerializer(serializers.ModelSerializer):
    company = CompanyListSerializer(read_only=True)
    role = serializers.CharField(read_only=True)

    class Meta:
        model = CompanyMembership
        fields = ('id', 'company', 'role', 'is_active', 'joined_at')


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)

    class Meta:
        model = KnowledgeDocument
        fields = (
            'id',
            'title',
            'content',
            'category',
            'tags',
            'is_published',
            'created_by',
            'created_by_email',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('created_by', 'created_at', 'updated_at')


class KnowledgeChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeChunk
        fields = (
            'id',
            'chunk_index',
            'text',
            'heading',
            'page_number',
            'slide_number',
            'token_count',
            'metadata',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class KnowledgeSourceDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.EmailField(source='uploaded_by.email', read_only=True)
    chunks_count = serializers.IntegerField(source='chunks.count', read_only=True)

    class Meta:
        model = KnowledgeSourceDocument
        fields = (
            'id',
            'title',
            'file',
            'file_type',
            'status',
            'content_hash',
            'error_message',
            'uploaded_by',
            'uploaded_by_email',
            'is_published',
            'indexed_at',
            'chunks_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'file_type',
            'status',
            'content_hash',
            'error_message',
            'uploaded_by',
            'uploaded_by_email',
            'indexed_at',
            'chunks_count',
            'created_at',
            'updated_at',
        )

    def validate_file(self, value):
        file_type = infer_file_type(value.name)
        if not file_type:
            raise serializers.ValidationError('Only PDF, DOCX, PPTX, and TXT files are supported.')
        return value

    def create(self, validated_data):
        uploaded_file = validated_data.get('file')
        validated_data['file_type'] = infer_file_type(uploaded_file.name)
        return super().create(validated_data)


class KnowledgeWebSourceSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    chunks_count = serializers.IntegerField(source='chunks.count', read_only=True)

    class Meta:
        model = KnowledgeWebSource
        fields = (
            'id',
            'title',
            'url',
            'crawl_mode',
            'crawl_depth',
            'max_pages',
            'refresh_interval',
            'status',
            'content_hash',
            'last_error',
            'last_crawled_at',
            'last_success_at',
            'next_crawl_at',
            'is_published',
            'created_by',
            'created_by_email',
            'chunks_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'status',
            'content_hash',
            'last_error',
            'last_crawled_at',
            'last_success_at',
            'next_crawl_at',
            'created_by',
            'created_by_email',
            'chunks_count',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        crawl_mode = attrs.get('crawl_mode') or getattr(self.instance, 'crawl_mode', None)
        crawl_depth = attrs.get('crawl_depth', getattr(self.instance, 'crawl_depth', 0))
        max_pages = attrs.get('max_pages', getattr(self.instance, 'max_pages', 1))
        if crawl_mode == KnowledgeWebSource.CrawlMode.SINGLE_PAGE:
            attrs['crawl_depth'] = 0
            attrs['max_pages'] = 1
        elif crawl_depth > 2:
            raise serializers.ValidationError({'crawl_depth': 'Maximum crawl depth is 2 for production safety.'})
        elif max_pages > 50:
            raise serializers.ValidationError({'max_pages': 'Maximum pages per crawl is 50.'})
        return attrs
