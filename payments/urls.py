from django.urls import path

from .views import (
    InitiatePaymentView,
    PaymentListView,
    PaymentStatusView,
    RecordPaymentView,
    ValidateAccountView,
)

urlpatterns = [
    path('payments/', PaymentListView.as_view(), name='payment-list'),
    path('payments/validate/', ValidateAccountView.as_view(), name='payment-validate'),
    path('payments/initiate/', InitiatePaymentView.as_view(), name='payment-initiate'),
    path('payments/record/', RecordPaymentView.as_view(), name='payment-record'),
    path('payments/<uuid:pk>/status/', PaymentStatusView.as_view(), name='payment-status'),
]
