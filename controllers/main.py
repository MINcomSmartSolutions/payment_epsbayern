import logging

from werkzeug.utils import redirect

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class EPSBayernController(http.Controller):
    _return_url = '/payment/epsbayern/return'

    @http.route(_return_url, type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def payment_return(self, **kwargs):
        """Handle the redirect back from the EPS Bayern paypage after payment."""
        _logger.info("EPS Bayern return with data: %s", kwargs)

        reference = kwargs.get('reference')
        if not reference:
            _logger.error("EPS Bayern return: missing reference parameter")
            _logger.debug("EPS Bayern return: full request data: %s", request)
            return redirect('/payment/status')

        notification_data = {'reference': reference}
        request.env['payment.transaction'].sudo()._handle_notification_data(
            'epsbayern', notification_data
        )

        return redirect('/payment/status')