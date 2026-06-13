import json
import logging
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db.models import Avg, Count, Sum
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from operations.services.audio import process_audio_message
from operations.services.text import _execute_tool, generate_text_reply, stream_text_reply
from operations.services.voice import create_realtime_session
from tenants.permissions import HasCompanyAccess, IsCompanyAgentOrAdmin, IsStaffUser

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
from .serializers import (
    BookingSerializer,
    CompanyMediaSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    EndCallSessionSerializer,
    FollowUpSerializer,
    MessageSerializer,
    OrderSerializer,
    RealtimeToolCallSerializer,
    SendAudioMessageSerializer,
    SendTextMessageSerializer,
    TicketCommentSerializer,
    TicketCreateUpdateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
)

logger = logging.getLogger(__name__)


def get_conversation_for_user(user, pk, staff_company=None):
    try:
        conversation = Conversation.objects.select_related('company', 'customer').get(pk=pk)
    except Conversation.DoesNotExist as exc:
        raise NotFound('Conversation not found.') from exc

    if user.user_type == 'customer':
        if conversation.customer_id != user.id:
            raise PermissionDenied('Not your conversation.')
    elif user.user_type == 'staff':
        if staff_company is None or conversation.company_id != staff_company.id:
            raise PermissionDenied('Conversation not in your active company.')
    elif user.user_type != 'platform_admin':
        raise PermissionDenied()
    return conversation


# --- Conversations ---


class CustomerConversationListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ConversationCreateSerializer
        return ConversationListSerializer

    def get_queryset(self):
        if self.request.user.user_type != 'customer':
            return Conversation.objects.none()
        return Conversation.objects.filter(customer=self.request.user).select_related('company')

    def perform_create(self, serializer):
        if self.request.user.user_type != 'customer':
            raise PermissionDenied('Only customers can start conversations.')
        serializer.save()


class OpenCustomerConversationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.user_type != 'customer':
            raise PermissionDenied('Only customers can start conversations.')

        serializer = ConversationCreateSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        company_id = serializer.validated_data['company_id']

        conversation = (
            Conversation.objects.filter(
                customer=request.user,
                company_id=company_id,
                status=Conversation.Status.ACTIVE,
            )
            .select_related('company', 'customer')
            .order_by('-updated_at', '-id')
            .first()
        )
        if conversation is None:
            conversation = serializer.save()

        return Response(
            ConversationListSerializer(
                conversation,
                context={'request': request},
            ).data,
            status=status.HTTP_200_OK,
        )


class StaffConversationListView(generics.ListAPIView):
    serializer_class = ConversationListSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]

    def get_queryset(self):
        qs = Conversation.objects.filter(company=self.request.company).select_related(
            'company', 'customer'
        )
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class ConversationDetailView(generics.RetrieveAPIView):
    serializer_class = ConversationDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        company = getattr(self.request, 'company', None)
        return get_conversation_for_user(self.request.user, self.kwargs['pk'], company)


class ConversationMessagesPageView(generics.ListAPIView):
    """
    Paginated message history endpoint for large conversations.
    Keeps existing conversation detail response intact for backward compatibility.
    """

    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        company = getattr(self.request, 'company', None)
        conversation = get_conversation_for_user(self.request.user, self.kwargs['pk'], company)
        return Message.objects.filter(conversation=conversation).order_by('created_at')


class SendTextMessageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = SendTextMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = getattr(request, 'company', None)
        conversation = get_conversation_for_user(request.user, pk, company)

        if conversation.status == Conversation.Status.CLOSED:
            raise ValidationError('Conversation is closed.')

        user_message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.CUSTOMER,
            content_type=Message.ContentType.TEXT,
            text_content=serializer.validated_data['text'],
        )

        try:
            reply_text, metadata = generate_text_reply(conversation, user_message.text_content)
        except Exception as exc:
            logger.exception('OpenAI text reply failed')
            reply_text = (
                'Your message has been received, but ChaliAssistant could not '
                'generate an automatic reply right now. A support agent can '
                'still review this conversation.'
            )
            metadata = {
                'source': 'fallback',
                'error': str(exc),
            }

        assistant_message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content_type=Message.ContentType.TEXT,
            text_content=reply_text,
            metadata=metadata,
        )
        conversation.save(update_fields=['updated_at'])

        return Response(
            {
                'user_message': MessageSerializer(user_message, context={'request': request}).data,
                'assistant_message': MessageSerializer(assistant_message, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StreamTextMessageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = SendTextMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = getattr(request, 'company', None)
        conversation = get_conversation_for_user(request.user, pk, company)

        if conversation.status == Conversation.Status.CLOSED:
            raise ValidationError('Conversation is closed.')

        user_message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.CUSTOMER,
            content_type=Message.ContentType.TEXT,
            text_content=serializer.validated_data['text'],
        )

        def event_stream():
            full_parts = []
            try:
                for chunk in stream_text_reply(conversation, user_message.text_content):
                    full_parts.append(chunk)
                    yield f'data: {json.dumps({"token": chunk})}\n\n'
            except Exception as exc:
                logger.exception('Streaming failed')
                yield f'data: {json.dumps({"error": str(exc)})}\n\n'
                return

            reply_text = ''.join(full_parts)
            assistant_message = Message.objects.create(
                conversation=conversation,
                role=Message.Role.ASSISTANT,
                content_type=Message.ContentType.TEXT,
                text_content=reply_text,
                metadata={'streamed': True},
            )
            conversation.save(update_fields=['updated_at'])
            yield f'data: {json.dumps({"done": True, "assistant_message_id": assistant_message.id})}\n\n'

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


class SendAudioMessageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = SendAudioMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = getattr(request, 'company', None)
        conversation = get_conversation_for_user(request.user, pk, company)

        if conversation.status == Conversation.Status.CLOSED:
            raise ValidationError('Conversation is closed.')

        audio = serializer.validated_data['audio']
        user_message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.CUSTOMER,
            content_type=Message.ContentType.AUDIO,
            audio_file=audio,
        )

        try:
            user_message.audio_file.open('rb')
            transcript, reply_text, reply_audio_bytes, metadata = process_audio_message(
                conversation,
                user_message.audio_file,
            )
        except Exception as exc:
            logger.exception('Audio message processing failed')
            raise ValidationError(f'Audio processing failed: {exc}') from exc
        finally:
            user_message.audio_file.close()

        user_message.audio_transcript = transcript
        user_message.save(update_fields=['audio_transcript'])

        assistant_message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content_type=Message.ContentType.AUDIO,
            text_content=reply_text,
            metadata=metadata,
        )
        assistant_message.audio_file.save(
            f'reply_{assistant_message.id}.mp3',
            ContentFile(reply_audio_bytes),
            save=True,
        )

        conversation.channel = Conversation.Channel.MIXED
        conversation.save(update_fields=['channel', 'updated_at'])

        return Response(
            {
                'user_message': MessageSerializer(user_message, context={'request': request}).data,
                'assistant_message': MessageSerializer(assistant_message, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class VoiceSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        company = getattr(request, 'company', None)
        conversation = get_conversation_for_user(request.user, pk, company)

        try:
            session_data = create_realtime_session(conversation)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            logger.exception('Realtime session creation failed')
            raise ValidationError(f'Voice session failed: {exc}') from exc

        call = CallSession.objects.create(
            conversation=conversation,
            openai_session_id=session_data.get('session_id', ''),
            metadata={'model': session_data.get('model'), 'voice': session_data.get('voice')},
        )
        conversation.channel = (
            Conversation.Channel.VOICE
            if conversation.channel == Conversation.Channel.CHAT
            else Conversation.Channel.MIXED
        )
        conversation.save(update_fields=['channel', 'updated_at'])

        return Response(
            {'call_session_id': call.id, **session_data},
            status=status.HTTP_201_CREATED,
        )


class EndCallSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, call_id):
        serializer = EndCallSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = getattr(request, 'company', None)
        conversation = get_conversation_for_user(request.user, pk, company)

        try:
            call = CallSession.objects.get(pk=call_id, conversation=conversation)
        except CallSession.DoesNotExist as exc:
            raise NotFound('Call session not found.') from exc

        call.status = CallSession.Status.COMPLETED
        call.ended_at = timezone.now()
        call.transcript = serializer.validated_data.get('transcript', [])
        call.duration_seconds = serializer.validated_data.get('duration_seconds')
        if serializer.validated_data.get('openai_session_id'):
            call.openai_session_id = serializer.validated_data['openai_session_id']
        call.save()

        if call.transcript:
            summary_lines = [
                f"{entry.get('role', 'unknown')}: {entry.get('text', '')}"
                for entry in call.transcript
                if entry.get('text')
            ]
            if summary_lines:
                Message.objects.create(
                    conversation=conversation,
                    role=Message.Role.SYSTEM,
                    content_type=Message.ContentType.TEXT,
                    text_content='Voice call transcript:\n' + '\n'.join(summary_lines),
                    metadata={'call_session_id': call.id},
                )

        return Response({'status': 'completed', 'call_session_id': call.id})


class RealtimeToolCallView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = RealtimeToolCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = getattr(request, 'company', None)
        conversation = get_conversation_for_user(request.user, pk, company)
        name = serializer.validated_data['name']
        arguments = serializer.validated_data.get('arguments') or {}

        if name not in {'search_knowledge_base', 'create_ticket'}:
            raise ValidationError('Realtime tool is not allowed.')

        result = _execute_tool(
            name,
            arguments,
            conversation.company,
            conversation,
            conversation.customer,
            realtime=True,
        )
        return Response(result)


# --- Tickets ---


class TicketViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    filterset_fields = ('status', 'priority', 'assigned_to', 'source')
    search_fields = ('ticket_number', 'title', 'description', 'customer__email')

    def get_queryset(self):
        return Ticket.objects.filter(company=self.request.company).select_related(
            'customer', 'assigned_to', 'conversation'
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TicketDetailSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return TicketCreateUpdateSerializer
        return TicketListSerializer

    def perform_create(self, serializer):
        serializer.save(company=self.request.company, source=Ticket.Source.STAFF)

    @action(detail=True, methods=['post'], url_path='comments')
    def add_comment(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = TicketComment.objects.create(
            ticket=ticket,
            author=request.user,
            body=serializer.validated_data['body'],
            is_internal=serializer.validated_data.get('is_internal', False),
        )
        return Response(TicketCommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='follow-ups')
    def follow_ups(self, request, pk=None):
        ticket = self.get_object()
        if request.method == 'GET':
            return Response(FollowUpSerializer(ticket.follow_ups.all(), many=True).data)

        serializer = FollowUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        follow_up = FollowUp.objects.create(ticket=ticket, **serializer.validated_data)
        return Response(FollowUpSerializer(follow_up).data, status=status.HTTP_201_CREATED)


class CustomerTicketListView(viewsets.ReadOnlyModelViewSet):
    serializer_class = TicketListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Ticket.objects.filter(customer=self.request.user).select_related('company')


# --- Orders & bookings ---


class StaffOrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    filterset_fields = ('status', 'customer')

    def get_queryset(self):
        if not self.request.company.enable_orders:
            return Order.objects.none()
        return Order.objects.filter(company=self.request.company).select_related('customer')

    def perform_create(self, serializer):
        if not self.request.company.enable_orders:
            raise ValidationError('Orders are not enabled for this company.')
        serializer.save(company=self.request.company)


class StaffBookingViewSet(viewsets.ModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    filterset_fields = ('status', 'customer')

    def get_queryset(self):
        if not self.request.company.enable_bookings:
            return Booking.objects.none()
        return Booking.objects.filter(company=self.request.company).select_related('customer')

    def perform_create(self, serializer):
        if not self.request.company.enable_bookings:
            raise ValidationError('Bookings are not enabled for this company.')
        serializer.save(company=self.request.company)


class CustomerOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user)


class CustomerBookingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(customer=self.request.user)


# --- Media ---


class CompanyMediaViewSet(viewsets.ModelViewSet):
    serializer_class = CompanyMediaSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    search_fields = ('title', 'description')

    def get_queryset(self):
        return CompanyMedia.objects.filter(company=self.request.company)

    def perform_create(self, serializer):
        serializer.save(company=self.request.company, created_by=self.request.user)


# --- Insights ---


class CompanyInsightsView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]

    def get(self, request):
        company = request.company
        now = timezone.now()
        last_30_days = now - timedelta(days=30)

        conversations = Conversation.objects.filter(company=company)
        recent_conversations = conversations.filter(created_at__gte=last_30_days)
        tickets = Ticket.objects.filter(company=company)
        open_tickets = tickets.filter(
            status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.PENDING]
        )
        msg_totals = conversations.aggregate(
            total_messages=Sum('message_count'),
            ai_messages=Sum('assistant_message_count'),
        )
        calls = CallSession.objects.filter(conversation__company=company)
        completed_calls = calls.filter(status=CallSession.Status.COMPLETED)
        pending_follow_ups = FollowUp.objects.filter(
            ticket__company=company,
            status=FollowUp.Status.PENDING,
        )

        data = {
            'period_days': 30,
            'conversations': {
                'total': conversations.count(),
                'last_30_days': recent_conversations.count(),
                'active': conversations.filter(status=Conversation.Status.ACTIVE).count(),
                'escalated': conversations.filter(status=Conversation.Status.ESCALATED).count(),
                'by_channel': list(conversations.values('channel').annotate(count=Count('id'))),
            },
            'messages': {
                'total': msg_totals.get('total_messages') or 0,
                'ai_replies': msg_totals.get('ai_messages') or 0,
            },
            'voice': {
                'total_calls': calls.count(),
                'completed_calls': completed_calls.count(),
                'avg_duration_seconds': completed_calls.aggregate(avg=Avg('duration_seconds'))['avg'],
            },
            'tickets': {
                'total': tickets.count(),
                'open': open_tickets.count(),
                'by_status': list(tickets.values('status').annotate(count=Count('id'))),
                'by_priority': list(tickets.values('priority').annotate(count=Count('id'))),
                'ai_created': tickets.filter(source=Ticket.Source.AI_AUTO).count(),
            },
            'follow_ups': {
                'pending': pending_follow_ups.count(),
                'overdue': pending_follow_ups.filter(due_date__lt=now).count(),
            },
            'media': {
                'total_assets': CompanyMedia.objects.filter(company=company).count(),
                'shareable': CompanyMedia.objects.filter(company=company, is_shareable=True).count(),
            },
        }

        if company.enable_orders:
            orders = Order.objects.filter(company=company)
            data['orders'] = {
                'total': orders.count(),
                'last_30_days': orders.filter(created_at__gte=last_30_days).count(),
                'by_status': list(orders.values('status').annotate(count=Count('id'))),
            }

        if company.enable_bookings:
            bookings = Booking.objects.filter(company=company)
            data['bookings'] = {
                'total': bookings.count(),
                'upcoming': bookings.filter(
                    scheduled_at__gte=now,
                    status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED],
                ).count(),
                'by_status': list(bookings.values('status').annotate(count=Count('id'))),
            }

        return Response(data)
