import logging
import math
import pprint

from werkzeug import urls

from odoo import _, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_epsbayern import const
from odoo.addons.payment_epsbayern.controllers.main import EPSBayernController

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    epsbayern_txn_id = fields.Char(string="EPS Bayern Transaction ID", readonly=True)

    # Nothing extra needed before rendering
    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != const.OUR_PROVIDER_CODE:
            return res
        return {}

    # Build cart, call createTxn, return redirect URL 
    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != const.OUR_PROVIDER_CODE:
            return res

        base_url = self.provider_id.get_base_url()
        return_url = urls.url_join(
            base_url,
            '%s?reference=%s' % (EPSBayernController._return_url, urls.url_quote(self.reference))
        )

        # Build cart
        cart = self._epsbayern_build_cart()
        _logger.debug("EPS Bayern cart for tx %s: %s", self.reference, pprint.pformat(cart))

        transaction_data = {
            'wdycf': return_url,
            'payMethodMask': '',
            'creditcardMask': '',
            'customerId': str(self.partner_id.id),
            'useRandomKey': '',
            'cart': cart,
        }

        payload = {'transaction': transaction_data}
        _logger.info(
            "EPS Bayern createTxn request for tx %s:\n%s",
            self.reference, pprint.pformat(payload)
        )

        response = self.provider_id._gateway_make_request(
            const.GATEWAY_API_ENDPOINTS['create_txn'], payload=payload
        )

        response_data = response.get('linkToPayPageResponseData', {})
        return_status = response_data.get('returnStatus', {})
        if return_status.get('returnCode', -1) != 0:
            raise ValidationError(
                "EPS Bayern: " + _(
                    "Failed to create transaction: %s",
                    response
                )
            )

        txn_id = response_data.get('txnId')
        url_to_paypage = response_data.get('urlToPayPage')

        if not txn_id or not url_to_paypage:
            raise ValidationError(
                "EPS Bayern: " + _("Gateway response missing txnId or urlToPayPage: %s", response)
            )

        self.epsbayern_txn_id = str(txn_id)
        self.provider_reference = str(txn_id)

        redirect_url = '%s?txnid=%s' % (url_to_paypage, txn_id)

        _logger.info(
            "EPS Bayern createTxn success for tx %s: txnId=%s, redirect=%s",
            self.reference, txn_id, redirect_url
        )
        
        # Sending it to the formview so user can be redirected 
        return {'api_url': redirect_url}

    def _epsbayern_build_cart(self):
        """Build the EPS Bayern cart payload from sale order lines, invoice lines, or transaction amount.

        Priority:
        1. sale_order_ids (direct SO payment) → use sale.order.line fields
        2. invoice_ids (invoice payment) → use account.move.line fields
        3. Fallback: single summary position from self.amount
        """
        _logger.debug("Building EPS Bayern cart for tx %s", self.reference)

        # 1. Try sale order lines
        if self.sale_order_ids:
            return self._epsbayern_cart_from_sale_orders(self.sale_order_ids)

        # 2. Try invoice lines
        #TODO: I'm not sure about this
        invoices = self.invoice_ids.filtered(
            lambda inv: inv.move_type in ('out_invoice', 'out_refund') # Need to look why out_refund?
        )
        if invoices:
            return self._epsbayern_cart_from_invoices(invoices)

        # 3. Fallback: single summary position
        _logger.warning("EPS Bayern: no sale orders or invoices for tx %s, using summary position", self.reference)
        return self._epsbayern_cart_fallback()

    def _epsbayern_cart_from_sale_orders(self, sale_orders):
        """Build cart from sale.order.line records."""
        positions = []
        vat_aggregation = {}
        pos_id = 0

        for order in sale_orders:
            for line in order.order_line:
                if line.display_type:
                    continue
                pos_id += 1
                qty = float(line.product_uom_qty)

                single_net = _to_cents(line.price_reduce_taxexcl)
                line_net = _to_cents(line.price_subtotal)
                line_vat = _to_cents(line.price_tax)
                line_gross = _to_cents(line.price_total)

                vat_rate = line.tax_id[0].amount if line.tax_id else 0.0

                positions.append({
                    'posId': pos_id,
                    'articleRef': (order.name or self.reference)[:30],
                    'articleDesc': (line.name or line.product_id.name or '')[:100],
                    'content': 1,
                    'singleNetAmount': single_net,
                    'number': qty,
                    'unit': (line.product_uom.name or 'Stk')[:30],
                    'sumNetAmount': line_net,
                    'vat': vat_rate,
                    'vatAmount': line_vat,
                    'grossAmount': line_gross,
                    'currency': self.currency_id.name,
                })

                vat_aggregation[vat_rate] = vat_aggregation.get(vat_rate, 0) + line_vat

        total_net = sum(_to_cents(o.amount_untaxed) for o in sale_orders)
        total_gross = sum(_to_cents(o.amount_total) for o in sale_orders)

        return self._epsbayern_assemble_cart(positions, vat_aggregation, total_net, total_gross)

    def _epsbayern_cart_from_invoices(self, invoices):
        """Build cart from account.move.line records, but only if all product lines are SO-linked.

        If any product line was manually added (no sale_line_ids), fall back to summary position
        since we cannot guarantee the cart accurately reflects the original sale orders.
        """
        all_product_lines = self.env['account.move.line']
        for invoice in invoices:
            all_product_lines |= invoice.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product'
            )

        if not all_product_lines:
            _logger.warning("EPS Bayern: invoices have no product lines for tx %s", self.reference)
            return self._epsbayern_cart_fallback()

        # Check that ALL product lines are linked to sale orders
        non_so_lines = all_product_lines.filtered(lambda l: not l.sale_line_ids)
        if non_so_lines:
            _logger.warning(
                "EPS Bayern: %d invoice line(s) not linked to sale orders for tx %s, using summary",
                len(non_so_lines), self.reference
            )
            return self._epsbayern_cart_fallback()

        positions = []
        vat_aggregation = {}
        pos_id = 0

        for line in all_product_lines:
                pos_id += 1
                qty = float(line.quantity)

                line_net = _to_cents(line.price_subtotal)
                line_gross = _to_cents(line.price_total)
                line_vat = line_gross - line_net
                single_net = _to_cents(line.price_subtotal / qty) if qty else line_net

                vat_rate = line.tax_ids[0].amount if line.tax_ids else 0.0
                so_name = line.sale_line_ids[0].order_id.name if line.sale_line_ids else self.reference

                positions.append({
                    'posId': pos_id,
                    'articleRef': so_name[:30],
                    'articleDesc': (line.name or line.product_id.name or '')[:100],
                    'content': 1,
                    'singleNetAmount': single_net,
                    'number': qty,
                    'unit': (line.product_uom_id.name or 'Stk')[:30],
                    'sumNetAmount': line_net,
                    'vat': vat_rate,
                    'vatAmount': line_vat,
                    'grossAmount': line_gross,
                    'currency': self.currency_id.name,
                })

                vat_aggregation[vat_rate] = vat_aggregation.get(vat_rate, 0) + line_vat

        total_net = sum(_to_cents(inv.amount_untaxed) for inv in invoices)
        total_gross = sum(_to_cents(inv.amount_total) for inv in invoices)

        return self._epsbayern_assemble_cart(positions, vat_aggregation, total_net, total_gross)

    def _epsbayern_cart_fallback(self):
        """Build a single summary position from the transaction amount."""
        amount_cents = _to_cents(self.amount)
        positions = [{
            'posId': 1,
            'articleRef': self.reference[:30],
            'articleDesc': (_("Payment %s", self.reference))[:100],
            'content': 1,
            'singleNetAmount': amount_cents,
            'number': 1,
            'unit': 'Stk',
            'sumNetAmount': amount_cents,
            'vat': 0.0,
            'vatAmount': 0,
            'grossAmount': amount_cents,
            'currency': self.currency_id.name,
        }]
        vat_aggregation = {0.0: 0}
        return self._epsbayern_assemble_cart(positions, vat_aggregation, amount_cents, amount_cents)

    def _epsbayern_assemble_cart(self, positions, vat_aggregation, total_net, total_gross):
        """Assemble the final cart dict with positions and VAT summary."""
        vat_positions = []
        for vat_pos_id, (rate, amount) in enumerate(vat_aggregation.items(), start=1):
            vat_positions.append({
                'posId': vat_pos_id,
                'vat': rate,
                'vatAmount': amount,
            })

        return {
            'cartRef': self.reference[:30],
            'totalNetAmount': total_net,
            'totalGrossAmount': total_gross,
            'currency': self.currency_id.name, # Should be ISO code like 'EUR' and even tough we do not support other currencies, this is dynamic
            'arrayOfPositions': positions,
            'arrayOfVatPosition': vat_positions,
        }

    # User came back. Find the transaction from notification/return data
    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != const.OUR_PROVIDER_CODE or len(tx) == 1: #Why len(tx) == 1?
            return tx

        reference = notification_data.get('reference')
        if not reference:
            raise ValidationError(
                "EPS Bayern: " + _("Received data with missing reference.")
            )

        tx = self.search([
            ('reference', '=', reference),
            ('provider_code', '=', const.OUR_PROVIDER_CODE),
        ])
        if not tx:
            raise ValidationError(
                "EPS Bayern: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    # Process notification → check status → auto-capture → update state ---
    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != const.OUR_PROVIDER_CODE:
            return

        if not self.provider_reference:
            raise ValidationError(
                "EPS Bayern: " + _("Transaction %s has no provider reference (txnId).", self.reference)
            )

        txn_id = int(self.provider_reference)

        # Query current transaction status
        status_response = self.provider_id._gateway_make_request(
            const.GATEWAY_API_ENDPOINTS['get_txn_status'],
            payload={'txnId': txn_id}
        )

        status_data = status_response.get('txnStatusResponseData', {})
        return_status = status_data.get('returnStatus', {})
        if return_status.get('returnCode', -1) != 0:
            _logger.error(
                "EPS Bayern getTxnStatus error for tx %s (txnId=%s): %s",
                self.reference, txn_id, return_status.get('returnMessage')
            )
            self._set_error(
                "EPS Bayern: " + _("Status check failed: %s", return_status.get('returnMessage', ''))
            )
            return

        txn_status = status_data.get('txnStatus', {})
        status_desc = txn_status.get('statusDesc', '')

        _logger.info(
            "EPS Bayern status for tx %s (txnId=%s): %s",
            self.reference, txn_id, status_desc
        )

        if status_desc in const.PAYMENT_STATUS_MAPPING['done']:
            # Already captured/booked
            self._set_done()
        elif status_desc in const.PAYMENT_STATUS_MAPPING['authorized']:
            # Reserved but not yet captured — auto-capture
            self._epsbayern_capture(txn_id)
        elif status_desc in const.PAYMENT_STATUS_MAPPING['cancel']:
            self._set_canceled()
        elif status_desc in const.PAYMENT_STATUS_MAPPING['pending']:
            self._set_pending()
        elif status_desc in const.PAYMENT_STATUS_MAPPING['error']:
            self._set_error(
                "EPS Bayern: " + _("Payment failed with status: %s", status_desc)
            )
        else:
            _logger.warning(
                "EPS Bayern unknown status '%s' for tx %s", status_desc, self.reference
            )
            self._set_error(
                "EPS Bayern: " + _("Received unknown payment status: %s", status_desc)
            )

    def _epsbayern_capture(self, txn_id):
        """Execute CAPTURE for an authorized (RESERVIERUNG_OK) transaction."""
        _logger.info(
            "EPS Bayern auto-capture for tx %s (txnId=%s)", self.reference, txn_id
        )
        try:
            capture_response = self.provider_id._gateway_make_request(
                const.GATEWAY_API_ENDPOINTS['execute'],
                payload={'command': 'CAPTURE', 'txnId': txn_id}
            )

            exec_data = capture_response.get('executeResponseData', {})
            base_response = exec_data.get('responseData', {}).get('baseResponseData', {})
            return_status = base_response.get('returnStatus', {})

            if return_status.get('returnCode', -1) != 0:
                _logger.error(
                    "EPS Bayern CAPTURE failed for tx %s: %s",
                    self.reference, return_status.get('returnMessage')
                )
                self._set_error(
                    "EPS Bayern: " + _(
                        "Capture failed: %s", return_status.get('returnMessage', '')
                    )
                )
                return

            _logger.info("EPS Bayern CAPTURE success for tx %s", self.reference)
            self._set_done()

        except ValidationError:
            _logger.exception("EPS Bayern CAPTURE request failed for tx %s", self.reference)
            self._set_error(
                "EPS Bayern: " + _("Capture request failed. Please check logs.")
            )

    # Handle refund requests from Odoo backend 
    # TODO: Needs testing
    def _send_refund_request(self, amount_to_refund=None):
        """Send a full refund (RETURN) via execute endpoint."""
        if self.provider_code != const.OUR_PROVIDER_CODE:
            return super()._send_refund_request(amount_to_refund=amount_to_refund)

        source_tx = self.source_transaction_id
        if not source_tx.provider_reference:
            raise ValidationError(
                "EPS Bayern: " + _("Cannot refund: source transaction has no provider reference.")
            )

        txn_id = int(source_tx.provider_reference)

        _logger.info(
            "EPS Bayern RETURN (refund) for tx %s, source txnId=%s",
            self.reference, txn_id
        )

        refund_response = self.provider_id._gateway_make_request(
            const.GATEWAY_API_ENDPOINTS['execute'],
            payload={'command': 'RETURN', 'txnId': txn_id}
        )

        exec_data = refund_response.get('executeResponseData', {})
        base_response = exec_data.get('responseData', {}).get('baseResponseData', {})
        return_status = base_response.get('returnStatus', {})

        if return_status.get('returnCode', -1) != 0:
            raise ValidationError(
                "EPS Bayern: " + _(
                    "Refund failed: %s", return_status.get('returnMessage', 'Unknown error')
                )
            )

        self.provider_reference = str(base_response.get('txnId', txn_id))

    # --- Cron: check stale pending transactions ---
    def _cron_epsbayern_check_stale_transactions(self):
        """Check pending EPS Bayern transactions and update their status."""
        timeout = const.STALE_TRANSACTION_TIMEOUT_MINUTES
        deadline = fields.Datetime.subtract(fields.Datetime.now(), minutes=timeout)
        stale_txs = self.search([
            ('provider_code', '=', const.OUR_PROVIDER_CODE),
            ('state', 'in', ('draft', 'pending')),
            ('provider_reference', '!=', False),
            ('create_date', '<', deadline),
        ])

        _logger.info(
            "EPS Bayern cron: checking %d stale transactions (older than %d min)",
            len(stale_txs), timeout
        )

        for tx in stale_txs:
            try:
                txn_id = int(tx.provider_reference)
                status_response = tx.provider_id._gateway_make_request(
                    const.GATEWAY_API_ENDPOINTS['get_txn_status'],
                    payload={'txnId': txn_id}
                )
                status_data = status_response.get('txnStatusResponseData', {})
                txn_status = status_data.get('txnStatus', {})
                status_desc = txn_status.get('statusDesc', '')

                _logger.info(
                    "EPS Bayern cron: tx %s (txnId=%s) status=%s",
                    tx.reference, txn_id, status_desc
                )

                if status_desc in const.PAYMENT_STATUS_MAPPING['done']:
                    tx._set_done()
                elif status_desc in const.PAYMENT_STATUS_MAPPING['authorized']:
                    tx._epsbayern_capture(txn_id)
                elif status_desc in const.PAYMENT_STATUS_MAPPING['cancel']:
                    tx._set_canceled()
                elif status_desc in const.PAYMENT_STATUS_MAPPING['error']:
                    tx._set_error(
                        "EPS Bayern: " + _("Payment failed with status: %s", status_desc)
                    )
                else:
                    # Still pending or unknown — try to abort
                    _logger.warning(
                        "EPS Bayern cron: aborting stale tx %s (txnId=%s, status=%s)",
                        tx.reference, txn_id, status_desc
                    )
                    try:
                        tx.provider_id._gateway_make_request(
                            const.GATEWAY_API_ENDPOINTS['abort_txn'],
                            payload={'txnId': txn_id}
                        )
                    except ValidationError:
                        _logger.exception(
                            "EPS Bayern cron: abort failed for tx %s", tx.reference
                        )
                    tx._set_canceled(
                        state_message=_("Transaction timed out and was aborted.")
                    )
            except Exception:
                _logger.exception(
                    "EPS Bayern cron: error processing stale tx %s", tx.reference
                )


def _to_cents(amount):
    """Convert a float amount to integer cents, rounding half-up."""
    return int(math.floor(amount * 100 + 0.5))
