"""
Payments API views.

Endpoints
---------
POST /api/payments/validate/      — validate account before charging
POST /api/payments/initiate/      — initiate payment (Pegasus STK push)
GET  /api/payments/<id>/status/   — poll payment status
POST /api/payments/record/        — record a locally-completed payment (Phase 1 bridge)
GET  /api/payments/               — list current user's payment history
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentTransaction
from .pegasus_client import PegasusClient
from .serializers import (
    InitiatePaymentSerializer,
    PaymentTransactionSerializer,
    RecordPaymentSerializer,
    ValidateAccountSerializer,
)

logger = logging.getLogger(__name__)


class ValidateAccountView(APIView):
    """
    POST /api/payments/validate/

    Calls Pegasus QueryCustomerDetails and returns the validated customer name.
    The mobile client uses this to show the "Account validated" step before charging.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        ser = ValidateAccountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        client = PegasusClient()
        result = client.validate_account(
            service_type=ser.validated_data['service_type'],
            account=ser.validated_data['account'],
            momo_network=ser.validated_data.get('momo_network', 'mtn'),
        )

        if result.success:
            return Response({
                'success': True,
                'customer_name': result.customer_name,
            })
        return Response(
            {'success': False, 'error': result.error},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class InitiatePaymentView(APIView):
    """
    POST /api/payments/initiate/

    Idempotent: if client_request_id already exists, returns the existing record.
    Otherwise creates a PaymentTransaction, calls Pegasus PostTransaction, and
    returns pending status.  The mobile client should poll /status/ to get the
    final result once the STK push completes.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        ser = InitiatePaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        # Idempotency guard
        existing = PaymentTransaction.objects.filter(
            client_request_id=d['client_request_id']
        ).first()
        if existing:
            return Response(PaymentTransactionSerializer(existing).data)

        tx = PaymentTransaction.objects.create(
            client_request_id=d['client_request_id'],
            user=request.user,
            service_type=d['service_type'],
            account=d['account'],
            amount=int(d['amount']),
            momo_network=d['momo_network'],
            momo_phone=d['momo_phone'],
            metadata=d.get('metadata') or {},
            status=PaymentTransaction.Status.PENDING,
        )

        client = PegasusClient()
        result = client.post_transaction(
            client_request_id=tx.client_request_id,
            service_type=tx.service_type,
            account=tx.account,
            amount=tx.amount,
            momo_network=tx.momo_network,
            momo_phone=tx.momo_phone,
        )

        tx.pegasus_reference = result.pegasus_reference
        tx.pegasus_response = result.raw
        if result.success:
            tx.status = PaymentTransaction.Status.PENDING
            if result.yaka_token:
                meta = tx.metadata or {}
                meta['yakaToken'] = result.yaka_token
                tx.metadata = meta
        else:
            tx.status = PaymentTransaction.Status.FAILED
        tx.save()

        if not result.success:
            return Response(
                {'error': result.error, 'id': str(tx.id)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            PaymentTransactionSerializer(tx).data,
            status=status.HTTP_201_CREATED,
        )


class PaymentStatusView(APIView):
    """
    GET /api/payments/<id>/status/

    Polls Pegasus GetTransactionDetails and updates + returns the local record.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: str) -> Response:
        try:
            tx = PaymentTransaction.objects.get(pk=pk, user=request.user)
        except PaymentTransaction.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        if tx.status == PaymentTransaction.Status.PENDING and tx.pegasus_reference:
            client = PegasusClient()
            result = client.get_transaction_status(tx.pegasus_reference)
            tx.status = {
                'completed': PaymentTransaction.Status.COMPLETED,
                'failed': PaymentTransaction.Status.FAILED,
            }.get(result.status, PaymentTransaction.Status.PENDING)
            if result.yaka_token:
                meta = tx.metadata or {}
                meta['yakaToken'] = result.yaka_token
                tx.metadata = meta
            tx.pegasus_response = result.raw
            tx.save()

        return Response(PaymentTransactionSerializer(tx).data)


class RecordPaymentView(APIView):
    """
    POST /api/payments/record/

    Bridge endpoint used while Phase 2 is not yet wired on the mobile side.
    The Flutter client records a payment that was processed locally (mock) so
    the server history stays in sync.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        ser = RecordPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        tx, created = PaymentTransaction.objects.get_or_create(
            client_request_id=d['client_request_id'],
            defaults={
                'user': request.user,
                'service_type': d['type'],
                'account': d.get('account', ''),
                'amount': int(d['amount']),
                'momo_network': d.get('momo_network', 'mtn').lower(),
                'momo_phone': d.get('momo_phone', ''),
                'reference': d.get('reference', ''),
                'status': d.get('status', 'completed'),
                'metadata': d.get('metadata') or {},
            },
        )

        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({'id': str(tx.id)}, status=code)


class PaymentListView(APIView):
    """
    GET /api/payments/

    Returns paginated payment history for the authenticated user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = PaymentTransaction.objects.filter(user=request.user)
        since = request.query_params.get('since')
        if since:
            try:
                from datetime import datetime, timezone
                since_dt = datetime.fromtimestamp(int(since) / 1000, tz=timezone.utc)
                qs = qs.filter(created_at__gte=since_dt)
            except (ValueError, TypeError):
                pass

        ser = PaymentTransactionSerializer(qs[:100], many=True)
        return Response({'results': ser.data, 'count': qs.count()})
