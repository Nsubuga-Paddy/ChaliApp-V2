from rest_framework import serializers

from tenants.serializers import absolute_media_url

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


class MessageSerializer(serializers.ModelSerializer):
    audio_file = serializers.SerializerMethodField()
    image_file = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = (
            'id',
            'role',
            'content_type',
            'text_content',
            'audio_file',
            'audio_transcript',
            'image_file',
            'metadata',
            'created_at',
        )
        read_only_fields = ('id', 'role', 'metadata', 'created_at')

    def get_audio_file(self, obj):
        return absolute_media_url(self, obj.audio_file)

    def get_image_file(self, obj):
        return absolute_media_url(self, obj.image_file)


class CallSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallSession
        fields = (
            'id',
            'openai_session_id',
            'status',
            'transcript',
            'duration_seconds',
            'started_at',
            'ended_at',
            'metadata',
        )
        read_only_fields = fields


class ConversationListSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    last_message_preview = serializers.CharField(read_only=True)

    class Meta:
        model = Conversation
        fields = (
            'id',
            'company',
            'company_name',
            'customer',
            'customer_email',
            'subject',
            'status',
            'channel',
            'assigned_to',
            'message_count',
            'assistant_message_count',
            'last_message_at',
            'last_message_preview',
            'created_at',
            'updated_at',
        )


class ConversationDetailSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    messages = MessageSerializer(many=True, read_only=True)
    call_sessions = CallSessionSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = (
            'id',
            'company',
            'company_name',
            'customer',
            'subject',
            'status',
            'channel',
            'assigned_to',
            'message_count',
            'assistant_message_count',
            'last_message_at',
            'last_message_preview',
            'messages',
            'call_sessions',
            'created_at',
            'updated_at',
            'closed_at',
        )


class ConversationCreateSerializer(serializers.ModelSerializer):
    company_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Conversation
        fields = ('id', 'company_id', 'subject', 'channel')
        read_only_fields = ('id',)

    def validate_company_id(self, value):
        from tenants.models import Company
        try:
            Company.objects.get(pk=value, is_active=True)
        except Company.DoesNotExist as exc:
            raise serializers.ValidationError('Company not found or inactive.') from exc
        return value

    def create(self, validated_data):
        from tenants.models import Company
        company_id = validated_data.pop('company_id')
        company = Company.objects.get(pk=company_id)
        return Conversation.objects.create(
            company=company,
            customer=self.context['request'].user,
            **validated_data,
        )


class SendTextMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000)


class SendAudioMessageSerializer(serializers.Serializer):
    audio = serializers.FileField()


class EndCallSessionSerializer(serializers.Serializer):
    transcript = serializers.ListField(child=serializers.DictField(), required=False)
    duration_seconds = serializers.IntegerField(required=False, min_value=0)
    openai_session_id = serializers.CharField(required=False, allow_blank=True)


class RealtimeToolCallSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    arguments = serializers.DictField(required=False)


class TicketCommentSerializer(serializers.ModelSerializer):
    author_email = serializers.EmailField(source='author.email', read_only=True)

    class Meta:
        model = TicketComment
        fields = ('id', 'author', 'author_email', 'body', 'is_internal', 'created_at')
        read_only_fields = ('author', 'created_at')


class FollowUpSerializer(serializers.ModelSerializer):
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True)

    class Meta:
        model = FollowUp
        fields = (
            'id',
            'title',
            'description',
            'due_date',
            'status',
            'assigned_to',
            'assigned_to_email',
            'created_at',
            'completed_at',
        )
        read_only_fields = ('created_at', 'completed_at')


class TicketListSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True)

    class Meta:
        model = Ticket
        fields = (
            'id',
            'ticket_number',
            'title',
            'status',
            'priority',
            'category',
            'source',
            'customer',
            'customer_email',
            'assigned_to',
            'assigned_to_email',
            'conversation',
            'created_at',
            'updated_at',
        )


class TicketDetailSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    comments = TicketCommentSerializer(many=True, read_only=True)
    follow_ups = FollowUpSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = (
            'id',
            'ticket_number',
            'title',
            'description',
            'status',
            'priority',
            'category',
            'source',
            'customer',
            'customer_email',
            'assigned_to',
            'conversation',
            'comments',
            'follow_ups',
            'created_at',
            'updated_at',
            'resolved_at',
        )


class TicketCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = (
            'title',
            'description',
            'status',
            'priority',
            'category',
            'assigned_to',
            'conversation',
            'customer',
        )


class OrderSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source='customer.email', read_only=True)

    class Meta:
        model = Order
        fields = (
            'id',
            'order_number',
            'company',
            'customer',
            'customer_email',
            'conversation',
            'status',
            'total_amount',
            'currency',
            'items',
            'notes',
            'metadata',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('order_number', 'created_at', 'updated_at')


class BookingSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source='customer.email', read_only=True)

    class Meta:
        model = Booking
        fields = (
            'id',
            'booking_number',
            'company',
            'customer',
            'customer_email',
            'conversation',
            'service_name',
            'scheduled_at',
            'status',
            'notes',
            'metadata',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('booking_number', 'created_at', 'updated_at')


class CompanyMediaSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)

    class Meta:
        model = CompanyMedia
        fields = (
            'id',
            'title',
            'description',
            'file',
            'is_shareable',
            'created_by',
            'created_by_email',
            'created_at',
        )
        read_only_fields = ('created_by', 'created_at')

    def get_file(self, obj):
        return absolute_media_url(self, obj.file)
