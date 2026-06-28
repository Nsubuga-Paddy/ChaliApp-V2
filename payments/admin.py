from django.contrib import admin

from .models import PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'service_type',
        'account',
        'amount_display',
        'momo_network',
        'momo_phone',
        'status',
        'pegasus_reference',
        'created_at',
    ]
    list_filter = ['status', 'service_type', 'momo_network', 'created_at']
    search_fields = ['account', 'momo_phone', 'pegasus_reference', 'client_request_id']
    readonly_fields = [
        'id',
        'client_request_id',
        'pegasus_reference',
        'pegasus_response',
        'created_at',
        'updated_at',
    ]
    ordering = ['-created_at']

    @admin.display(description='Amount (UGX)')
    def amount_display(self, obj: PaymentTransaction) -> str:
        return f'UGX {obj.amount:,}'
