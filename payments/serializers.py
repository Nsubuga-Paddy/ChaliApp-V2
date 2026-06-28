from rest_framework import serializers

from .models import PaymentTransaction


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            'id',
            'client_request_id',
            'service_type',
            'account',
            'amount',
            'momo_network',
            'momo_phone',
            'pegasus_reference',
            'reference',
            'status',
            'metadata',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'pegasus_reference',
            'status',
            'created_at',
            'updated_at',
        ]


class ValidateAccountSerializer(serializers.Serializer):
    service_type = serializers.ChoiceField(
        choices=['yaka', 'water', 'airtime', 'tv', 'school', 'ura']
    )
    account = serializers.CharField(max_length=128)
    momo_network = serializers.ChoiceField(
        choices=['mtn', 'airtel'], default='mtn', required=False
    )


class InitiatePaymentSerializer(serializers.Serializer):
    client_request_id = serializers.CharField(max_length=64)
    service_type = serializers.ChoiceField(
        choices=['yaka', 'water', 'airtime', 'tv', 'school', 'ura']
    )
    account = serializers.CharField(max_length=128)
    amount = serializers.IntegerField(min_value=500)
    momo_network = serializers.ChoiceField(choices=['mtn', 'airtel'])
    momo_phone = serializers.CharField(max_length=20)
    metadata = serializers.DictField(required=False, allow_null=True, default=dict)


class RecordPaymentSerializer(serializers.Serializer):
    """Used by the Flutter client to record a locally-completed payment."""
    client_request_id = serializers.CharField(max_length=64)
    type = serializers.ChoiceField(
        choices=['yaka', 'water', 'airtime', 'tv', 'school', 'ura']
    )
    amount = serializers.FloatField(min_value=0)
    account = serializers.CharField(max_length=128, default='')
    momo_network = serializers.ChoiceField(
        choices=['mtn', 'airtel', 'MTN', 'Airtel'], default='mtn'
    )
    momo_phone = serializers.CharField(max_length=20, default='')
    reference = serializers.CharField(max_length=64, default='')
    status = serializers.ChoiceField(
        choices=['pending', 'completed', 'failed'], default='completed'
    )
    metadata = serializers.DictField(required=False, allow_null=True, default=dict)
