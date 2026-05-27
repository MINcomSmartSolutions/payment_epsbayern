import logging
import os
_logger = logging.getLogger(__name__)

# DO NOT CHANGE IT! Here for the easy access, not for the config.
EPSBAYERN_PROVIDER_CODE = 'epsbayern'

SUPPORTED_CURRENCIES = [
    'EUR',
]

SUPPORTED_COUNTRIES = {
    'DE'
}

DEFAULT_PAYMENT_METHOD_CODES = {
    # Actually it is; paypal, visa, mastercard, sepa, but the diffrantiate is not needed for odoo and would be over
    # engineered
    'epsbayern',
}

GATEWAY_API_BASE_URL = {
    'enabled': os.environ.get('EPS_BAYERN_PROD_GATEWAY_API_BASE_URL', 'https://epaybs-gateway.it.admin.edu'),
    'test': os.environ.get('EPS_BAYERN_TEST_GATEWAY_API_BASE_URL', 'https://epaybs-gateway-stage.it.admin.hm.edu'),
}

EPS_BASE_URLS = { # to validate redirection
    'enabled':  'https://epayservice-itdlz.bayern.de',
    'test': 'https://epayservice-test-itdlz.bayern.de',
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
        'REDIRECT_PAYPAGE_ABBRUCH',
        'RESERVIERUNG_ABBRUCH'
    },
    'error': {
        'RESERVIERUNG_FEHLSCHLAG', # This can also be "cancel" but hard to say whether the txn was canceled by user or
        # something went wrong
        'BUCHUNG_NICHT_OK',
        'RESERVIERUNG_NICHT_OK',
        'IHV_NICHT_OK',
        'REDIRECT_PAYPAGE_NICHT_OK',
        'START_NICHT_OK',
    },
}

# Timeout in hours after which pending transactions are considered stale
STALE_TRANSACTION_TIMEOUT_HOURS = 48
if os.getenv('ODOO_ENV', 'dev') == 'dev':
    STALE_TRANSACTION_TIMEOUT_HOURS = 1