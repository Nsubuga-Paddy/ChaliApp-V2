"""
Payment models for Chali Mobile.

All payments go through the Pegasus aggregator (MoMo collections).
No wallet balance is stored here — Chali never holds user funds.
"""

import uuid

from django.conf import settings
from django.db import models


class PaymentTransaction(models.Model):
    """Records a single utility / airtime payment made via Pegasus."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        REVERSED = 'reversed', 'Reversed'

    class MomoNetwork(models.TextChoices):
        MTN = 'mtn', 'MTN MoMo'
        AIRTEL = 'airtel', 'Airtel Money'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Idempotency key sent by the mobile client
    client_request_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text='Client-generated idempotency key (prevents double-charges on retry).',
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payment_transactions',
        null=True,
        blank=True,
    )

    # Service type: yaka, water, airtime, tv, school, ura
    service_type = models.CharField(max_length=32)

    # Account/meter/phone being paid for
    account = models.CharField(max_length=128)

    amount = models.PositiveIntegerField(help_text='Amount in UGX (no decimals).')

    momo_network = models.CharField(
        max_length=16,
        choices=MomoNetwork.choices,
        default=MomoNetwork.MTN,
    )

    # Mobile money phone that received the STK push
    momo_phone = models.CharField(max_length=20)

    # Pegasus transaction reference (from PostTransaction response)
    pegasus_reference = models.CharField(max_length=128, blank=True)

    # Internal client reference echoed back
    reference = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Full Pegasus API response stored for debugging
    pegasus_response = models.JSONField(null=True, blank=True)

    # Extra data: e.g. Yaka token, validated customer name
    metadata = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment transaction'
        verbose_name_plural = 'Payment transactions'

    def __str__(self):
        return (
            f'{self.service_type.upper()} | {self.account} | '
            f'UGX {self.amount:,} | {self.status}'
        )
