"""
Pegasus Technologies payment gateway client.

All calls are made over HTTPS to the Pegasus SOAP/XML API.
Sandbox and production endpoints are selected via Django settings:

    PEGASUS_BASE_URL      — e.g. https://sandbox.pegasusgateway.com/
    PEGASUS_USERNAME      — your vendor username
    PEGASUS_PASSWORD      — your vendor password
    PEGASUS_VENDOR_CODE   — assigned vendor code

Phase 2 implements:
  • QueryCustomerDetails  — validate account before charging
  • PostTransaction        — initiate STK push + post payment
  • GetTransactionDetails  — poll for final status

Usage
-----
    from payments.pegasus_client import PegasusClient
    client = PegasusClient()
    result = client.validate_account(service_type='yaka', account='04123456789')
    result = client.post_transaction(...)
"""

import logging
import uuid
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg(name: str, default: str = '') -> str:
    return getattr(settings, name, default) or default


# Pegasus biller codes (Ugandan standard service codes).
# Update these once Pegasus confirms your vendor mapping.
BILLER_CODES: dict[str, str] = {
    'yaka': getattr(settings, 'PEGASUS_BILLER_YAKA', 'YAKA'),
    'water': getattr(settings, 'PEGASUS_BILLER_WATER', 'NWSC'),
    'airtime_mtn': getattr(settings, 'PEGASUS_BILLER_AIRTIME_MTN', 'MTNAIRTIME'),
    'airtime_airtel': getattr(settings, 'PEGASUS_BILLER_AIRTIME_AIRTEL', 'AIRTELAIRTIME'),
    'tv': getattr(settings, 'PEGASUS_BILLER_TV', 'DSTV'),
    'school': getattr(settings, 'PEGASUS_BILLER_SCHOOL', 'SCHOOLFEES'),
    'ura': getattr(settings, 'PEGASUS_BILLER_URA', 'URA'),
}


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    success: bool
    customer_name: str = ''
    error: str = ''
    raw: dict | None = None


@dataclass
class TransactionResult:
    success: bool
    pegasus_reference: str = ''
    status: str = 'pending'
    yaka_token: str = ''
    error: str = ''
    raw: dict | None = None


# ── Client ────────────────────────────────────────────────────────────────────

class PegasusClient:
    """Thin wrapper around the Pegasus REST/SOAP gateway."""

    def __init__(self) -> None:
        self.base_url = _cfg('PEGASUS_BASE_URL', 'https://sandbox.pegasusgateway.com').rstrip('/')
        self.username = _cfg('PEGASUS_USERNAME')
        self.password = _cfg('PEGASUS_PASSWORD')
        self.vendor_code = _cfg('PEGASUS_VENDOR_CODE')
        self.timeout = int(_cfg('PEGASUS_TIMEOUT', '30'))

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.auth = (self.username, self.password)
        s.headers.update({'Content-Type': 'application/json', 'Accept': 'application/json'})
        return s

    def _biller_code(self, service_type: str, momo_network: str = 'mtn') -> str:
        if service_type == 'airtime':
            key = f'airtime_{momo_network.lower()}'
            return BILLER_CODES.get(key, BILLER_CODES['airtime_mtn'])
        return BILLER_CODES.get(service_type, service_type.upper())

    # ── QueryCustomerDetails ────────────────────────────────────────────────

    def validate_account(
        self,
        service_type: str,
        account: str,
        momo_network: str = 'mtn',
    ) -> ValidationResult:
        """
        Calls Pegasus QueryCustomerDetails to validate an account/meter number
        before charging.  Returns the customer name on success.
        """
        if not self.username:
            # Credentials not configured — return a mock result in dev
            logger.warning('Pegasus credentials not configured; returning mock validate result.')
            return ValidationResult(
                success=True,
                customer_name=f'Account {account}',
                raw={'mock': True},
            )

        biller = self._biller_code(service_type, momo_network)
        payload = {
            'VendorCode': self.vendor_code,
            'BillerCode': biller,
            'AccountNumber': account,
        }
        try:
            resp = self._session().post(
                f'{self.base_url}/api/QueryCustomerDetails',
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data: dict = resp.json()
            logger.debug('Pegasus validate response: %s', data)

            if data.get('ResponseCode') in ('0', '00', 0):
                return ValidationResult(
                    success=True,
                    customer_name=data.get('CustomerName', account),
                    raw=data,
                )
            return ValidationResult(
                success=False,
                error=data.get('ResponseMessage', 'Validation failed'),
                raw=data,
            )
        except requests.RequestException as exc:
            logger.exception('Pegasus validate_account error')
            return ValidationResult(success=False, error=str(exc))

    # ── PostTransaction ─────────────────────────────────────────────────────

    def post_transaction(
        self,
        *,
        client_request_id: str,
        service_type: str,
        account: str,
        amount: int,
        momo_network: str,
        momo_phone: str,
    ) -> TransactionResult:
        """
        Initiates an STK push + utility payment via Pegasus PostTransaction.
        Returns the Pegasus reference for subsequent status polling.
        """
        if not self.username:
            logger.warning('Pegasus credentials not configured; returning mock transaction result.')
            ref = f'MOCK-{uuid.uuid4().hex[:8].upper()}'
            return TransactionResult(
                success=True,
                pegasus_reference=ref,
                status='completed',
                yaka_token='',
                raw={'mock': True, 'reference': ref},
            )

        biller = self._biller_code(service_type, momo_network)
        payload = {
            'VendorCode': self.vendor_code,
            'BillerCode': biller,
            'AccountNumber': account,
            'Amount': amount,
            'MobileNetwork': momo_network.upper(),
            'MobileNumber': momo_phone,
            'ClientReference': client_request_id,
            'Narration': f'Chali {service_type} payment',
        }
        try:
            resp = self._session().post(
                f'{self.base_url}/api/PostTransaction',
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data: dict = resp.json()
            logger.debug('Pegasus post_transaction response: %s', data)

            if data.get('ResponseCode') in ('0', '00', 0):
                return TransactionResult(
                    success=True,
                    pegasus_reference=data.get('TransactionReference', ''),
                    status='pending',
                    yaka_token=data.get('YakaToken', ''),
                    raw=data,
                )
            return TransactionResult(
                success=False,
                error=data.get('ResponseMessage', 'Transaction failed'),
                raw=data,
            )
        except requests.RequestException as exc:
            logger.exception('Pegasus post_transaction error')
            return TransactionResult(success=False, error=str(exc))

    # ── GetTransactionDetails ───────────────────────────────────────────────

    def get_transaction_status(self, pegasus_reference: str) -> TransactionResult:
        """
        Polls Pegasus for the final status of a previously submitted transaction.
        Call this from a Celery task a few seconds after post_transaction.
        """
        if not self.username:
            return TransactionResult(
                success=True,
                pegasus_reference=pegasus_reference,
                status='completed',
                raw={'mock': True},
            )

        payload = {
            'VendorCode': self.vendor_code,
            'TransactionReference': pegasus_reference,
        }
        try:
            resp = self._session().post(
                f'{self.base_url}/api/GetTransactionDetails',
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data: dict = resp.json()
            logger.debug('Pegasus get_transaction_status response: %s', data)

            rc = str(data.get('ResponseCode', ''))
            status = 'completed' if rc in ('0', '00') else 'pending' if rc == '1' else 'failed'
            return TransactionResult(
                success=status != 'failed',
                pegasus_reference=pegasus_reference,
                status=status,
                yaka_token=data.get('YakaToken', ''),
                raw=data,
            )
        except requests.RequestException as exc:
            logger.exception('Pegasus get_transaction_status error')
            return TransactionResult(
                success=False,
                pegasus_reference=pegasus_reference,
                status='failed',
                error=str(exc),
            )
