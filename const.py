import logging
import os
_logger = logging.getLogger(__name__)

EPSBAYERN_PROVIDER_CODE = 'epsbayern' # Do not change it! Here for the easy access, not for the config.

SUPPORTED_CURRENCIES = (
    'EUR',
)
SUPPORTED_COUNTRIES = {
    'DE'
}

DEFAULT_PAYMENT_METHOD_CODES = {
    'epsbayern',
}

GATEWAY_API_BASE_URL = {
    #TODO: Change 'enabled' to prod url or env variable
    'enabled': os.environ.get('EPS_BAYERN_PROD_GATEWAY_API_BASE_URL'),
    'test': os.environ.get('EPS_BAYERN_TEST_GATEWAY_API_BASE_URL'),
}

EPS_BASE_URLS = { # to validate redirection
    # TODO: Change 'enabled' to prod url or env variable
    'enabled': os.environ.get('EPS_BAYERN_PROD_EPS_BASE_URL', ''),
    'test': os.environ.get('EPS_BAYERN_TEST_EPS_BASE_URL', ''),
}

if GATEWAY_API_BASE_URL['test'].startswith('http://') or GATEWAY_API_BASE_URL['enabled'].startswith('http://'):
    _logger.error('The base urls should not be using insecure http')


GATEWAY_API_ENDPOINTS = {
    'create_txn': '/v1/payment/createTxn',
    'get_txn_status': '/v1/payment/getTxnStatus',
    'get_txn_status_detail': '/v1/payment/getTxnStatusDetail',
    'execute': '/v1/payment/execute',
    'cancel_return': '/v1/payment/cancelReturn',
    'abort_txn': '/v1/payment/abortTxn',
    'get_pay_services': '/v1/payment/getPayServices',
}

# Maps EPS Bayern statusDesc values to Odoo payment transaction states.
# See getTxnStatusDetail for the full lifecycle of status transitions.
PAYMENT_STATUS_MAPPING = {
    'pending': {
        'START_OK',
        'IHV_BEGINN',
        'IHV_OK',
        'REDIRECT_PAYPAGE_BEGINN',
        'REDIRECT_PAYPAGE_OK',
        'RESERVIERUNG_BEGINN',
        'BUCHUNG_BEGINN',
    },
    'authorized': {
        'RESERVIERUNG_OK',
    },
    'done': {
        'BUCHUNG_OK',
    },
    'cancel': {
        'STORNO_OK',
        'ABBRUCH_OK',
    },
    'error': {
        'RESERVIERUNG_FEHLSCHLAG',
        'BUCHUNG_NICHT_OK',
        'RESERVIERUNG_NICHT_OK',
        'IHV_NICHT_OK',
        'REDIRECT_PAYPAGE_NICHT_OK',
        'START_NICHT_OK',
    },
}

# Timeout in minutes after which pending transactions are considered stale
STALE_TRANSACTION_TIMEOUT_MINUTES = 60
# Timeout in hours after which pending transactions are considered stale
STALE_TRANSACTION_TIMEOUT_HOURS = 48