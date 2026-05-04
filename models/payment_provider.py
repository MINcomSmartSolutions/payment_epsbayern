import logging
import os
import pprint

import requests
from werkzeug import urls

from odoo import _, fields, models
from odoo.addons.payment_epsbayern import const
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    if 'epsbayern' != const.EPSBAYERN_PROVIDER_CODE:
        raise ValidationError(
            "The provider code in const.py does not match the one in the model. Please set it to 'epsbayern'."
        )

    code = fields.Selection(
        selection_add=[('epsbayern', "ePayServiceBayern")],
        ondelete={'epsbayern': 'set default'},
    )

    # Here we can define extra secrets or ids as fields but since gateway handles those and since we will switch to
    # per individual user based auth, we do not need this part.

    # Declare feature support
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == const.EPSBAYERN_PROVIDER_CODE).update({
            'support_refund': 'full_only',
        })

    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code != const.EPSBAYERN_PROVIDER_CODE:
            return default_codes
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_supported_currencies(self):
        supported_currencies = super()._get_supported_currencies()
        if self.code == const.EPSBAYERN_PROVIDER_CODE:
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _gateway_make_request(self, endpoint, method='POST', payload=None, authenticated=True):
        """ Returns the json-encoded content of a response, if any.
        :param endpoint:
        :param method:
        :param payload:
        :param authenticated:
        :return:
        """
        self.ensure_one()

        accepted_methods = ['get', 'post', 'put', 'patch', 'delete']

        if method.lower() not in accepted_methods:
            raise ValidationError(
                "EPS Bayern: " + _("Invalid HTTP method '%s' for gateway request.") % method
            )

        url = urls.url_join(self._gateway_get_api_url(), endpoint)

        headers = {'Content-Type': 'application/json'}

        if payload is not None and method.upper() == 'GET':
            raise ValidationError(
                "EPS Bayern: " + _("GET requests to the gateway with payload is not supported.")
            )

        if authenticated:
            headers['Authorization'] = f'Bearer {self._get_access_token()}'

        response = None
        try:
            response = requests.request(method, url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            _logger.exception("Unable to reach endpoint at %s", url)
            raise ValidationError(
                "EPS Bayern: " + _("Could not establish the connection to the gateway.")
            )
        except requests.exceptions.HTTPError:
            raise self._user_friendly_error_process(response)

        return response.json()

    def _gateway_get_api_url(self):
        self.ensure_one()
        url = const.GATEWAY_API_BASE_URL.get(self.state, const.GATEWAY_API_BASE_URL['test'])
        return url

    # TODO: For now, it does authentication with gateway provided username pw to obtain jwt tokens but for the future it
    # should work individual user based jwt tokens that comes from HM OIDC.
    def _get_access_token(self):
        username, token = self._get_gateway_credentials()
        return token  # for now implementation is just bearer token

    def _get_gateway_credentials(self):
        username = os.environ.get('HM_PAYMENT_GATEWAY_API_USER')
        token = os.environ.get('HM_PAYMENT_GATEWAY_API_TOKEN')
        if not username or not token:
            _logger.error("Gateway credentials are not configured in environment variables.")
            raise ValidationError(
                "EPS Bayern: " + _("Gateway credentials are missing")
            )
        return username, token

    def _user_friendly_error_process(self, response):
        if response is None:
            _logger.warning("EPS Bayern: Empty response received for _raise_for_error")

        try:
            response_data = response.json()
        except ValueError:
            response_data = response.text
            _logger.error("EPS Bayern: Non-JSON response received. Raw text: %s", response_data)

        if response.ok:
            _logger.warning("EPS Bayern: No need to raise for response, %s, with status %s", response_data,
                            response.status_code)

        if isinstance(response_data, dict):
            details = response_data.get('details', None)
            error = response_data.get('error', None)
            message = response_data.get('message', None)
            if details:
                errorCode = details.get('errorCode', None)
                methodName = details.get('methodName', None)
                erroredTxnid = details.get('txnId', None)
                _logger.error(
                    "EPS Bayern: API request error with details - errorCode: %s, methodName: %s, txnId: %s",
                    errorCode, methodName, erroredTxnid
                )
                if "Transaktion ist bereits storniert" in message:
                    _logger.error("EPS Bayern: TXN is already cancelled, cannot proceed with refund/cancellation.")
                    return ValidationError(
                        "EPS Bayern: " + _("Transaction %s is already cancelled, cannot proceed with refund.", erroredTxnid)
                    )

            if error:
                if error == 'UNAUTHORIZED':
                    _logger.error("EPS Bayern: Unauthorized access - likely due to missing or invalid credentials.")
                else:
                    _logger.error("EPS Bayern: " + str(error))

        _logger.exception("Invalid API request at %s, Status Code: %s, Response Data: %s", response.request.url,
                          response.status_code, pprint.pformat(response_data))

        return ValidationError(
            "EPS Bayern: " + _(
                "The communication with the gateway failed, please try again later. Sorry for the inconvenience.")
        )
