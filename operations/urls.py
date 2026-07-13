from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanyInsightsView,
    CompanyMenuView,
    CompanyMediaViewSet,
    ConversationDetailView,
    ConversationMessagesPageView,
    CustomerBookingViewSet,
    CustomerConversationListCreateView,
    CustomerOrderViewSet,
    CustomerTicketListView,
    EndCallSessionView,
    OpenCustomerConversationView,
    RealtimeToolCallView,
    SendAudioMessageView,
    SendTextMessageView,
    StaffBookingViewSet,
    StaffConversationListView,
    StaffOrderViewSet,
    StreamTextMessageView,
    TicketViewSet,
    VoiceSessionView,
)

router = DefaultRouter()
router.register(r'staff/tickets', TicketViewSet, basename='staff-ticket')
router.register(r'my-tickets', CustomerTicketListView, basename='customer-ticket')
router.register(r'staff/orders', StaffOrderViewSet, basename='staff-order')
router.register(r'staff/bookings', StaffBookingViewSet, basename='staff-booking')
router.register(r'my-orders', CustomerOrderViewSet, basename='customer-order')
router.register(r'my-bookings', CustomerBookingViewSet, basename='customer-booking')
router.register(r'staff/media', CompanyMediaViewSet, basename='staff-media')

urlpatterns = [
    path('conversations/', CustomerConversationListCreateView.as_view(), name='conversation-list'),
    path('conversations/open/', OpenCustomerConversationView.as_view(), name='conversation-open'),
    path('conversations/<int:pk>/', ConversationDetailView.as_view(), name='conversation-detail'),
    path(
        'conversations/<int:pk>/messages/page/',
        ConversationMessagesPageView.as_view(),
        name='conversation-messages-page',
    ),
    path('conversations/<int:pk>/messages/', SendTextMessageView.as_view(), name='conversation-send-text'),
    path(
        'conversations/<int:pk>/messages/stream/',
        StreamTextMessageView.as_view(),
        name='conversation-stream-text',
    ),
    path(
        'conversations/<int:pk>/messages/audio/',
        SendAudioMessageView.as_view(),
        name='conversation-send-audio',
    ),
    path(
        'conversations/<int:pk>/voice-session/',
        VoiceSessionView.as_view(),
        name='conversation-voice-session',
    ),
    path(
        'conversations/<int:pk>/calls/<int:call_id>/end/',
        EndCallSessionView.as_view(),
        name='conversation-end-call',
    ),
    path(
        'conversations/<int:pk>/voice-session/tool/',
        RealtimeToolCallView.as_view(),
        name='conversation-realtime-tool',
    ),
    path('staff/conversations/', StaffConversationListView.as_view(), name='staff-conversation-list'),
    path('staff/insights/', CompanyInsightsView.as_view(), name='company-insights'),
    path('companies/<int:company_id>/menu/', CompanyMenuView.as_view(), name='company-menu'),
    path('', include(router.urls)),
]
