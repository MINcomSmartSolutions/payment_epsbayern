# see: Module addons.payment.models.payment_transaction

import json
import logging
import pprint

from werkzeug import urls

from odoo import _, fields, models
from odoo.addons.payment_epsbayern import const
from odoo.addons.payment_epsbayern.controllers.main import EPSBayernController
from odoo.addons.payment_epsbayern.utils import _to_cents, _sanitize_ref, _add_prefix_to_ref, CartPosition, VatPosition, \
    Cart, _successfull_return_status
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    epsbayern_sanitized_ref = fields.Char(string="Sanitized Custom Reference", readonly=True)

    # Nothing extra needed before rendering
    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != const.EPSBAYERN_PROVIDER_CODE:
            return res
        return {}

    # Build cart, call createTxn, return redirect URL
    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != const.EPSBAYERN_PROVIDER_CODE:
            return res

        self.epsbayern_sanitized_ref = _add_prefix_to_ref(_sanitize_ref(self.reference))

        base_url = self.provider_id.get_base_url()
        db_secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        return_sig = EPSBayernController._compute_return_hmac(self.epsbayern_sanitized_ref, db_secret)
        return_url = urls.url_join(
            base_url,
            '%s?reference=%s&sig=%s' % (
                EPSBayernController._return_url,
                self.epsbayern_sanitized_ref,
                return_sig,
            )
        )

        cart = self._epsbayern_build_cart()
        _logger.debug("EPS Bayern cart for tx %s: %s", self.reference, pprint.pformat(cart))

        transaction_data = {
            'wdycf': return_url,
            'customerId': str(self.partner_id.id),
            'cart': cart,
        }

        ihv_data = self._epsbayern_build_ihv_data()
        hkr_data = self._epsbayern_build_hkr_data()

        payload = {'transaction': transaction_data, 'hkr': hkr_data, 'ihvV230Data': ihv_data}

        _logger.info(
            "EPS Bayern createTxn request for tx %s:\n%s",
            self.reference, pprint.pformat(payload)
        )

        response = self.provider_id._gateway_make_request(
            const.GATEWAY_API_ENDPOINTS['create_txn'], payload=payload
        )

        response_data = response.get('linkToPayPageResponseData', {})
        return_status = response_data.get('returnStatus', {})
        if not _successfull_return_status(return_status):
            raise ValidationError(
                "EPS Bayern: " + _(
                    "Failed to create transaction: %s",
                    pprint.pformat(response.json())
                )
            )

        eps_txn_id = response_data.get('txnId')
        url_to_paypage = response_data.get('urlToPayPage')

        if not eps_txn_id or not url_to_paypage:
            raise ValidationError(
                "EPS Bayern: " + _("Gateway response missing txnId or urlToPayPage: %s", pprint.pformat(response.json())
                                   ))

        # Validate redirect URL
        allowed_bases = (
            const.EPS_BASE_URLS.get('enabled', ''),
            const.EPS_BASE_URLS.get('test', ''),
        )
        if not any(url_to_paypage.startswith(base) for base in allowed_bases if base):
            raise ValidationError(
                "EPS Bayern: " + _(
                    "Gateway returned untrusted paypage URL: %s", url_to_paypage
                )
            )

        self.provider_reference = str(eps_txn_id)

        redirect_url = '%s?txnid=%s' % (url_to_paypage, eps_txn_id)

        _logger.info(
            "EPS Bayern createTxn success for tx %s: txnId=%s, redirect=%s",
            self.reference, eps_txn_id, redirect_url
        )

        # Sending it to the formview so user can be redirected
        # Pass base URL and txnid separately so the GET form can include
        # the txnid as a hidden field (method="get" forms strip query params
        # from the action URL).
        return {
            'api_url': url_to_paypage,
            'txnid': str(eps_txn_id),
        }

    def _epsbayern_build_ihv_data(self):
        """Build the IHV V230 data payload for the createTxn request.

        Populates customer fields from the transaction partner and basic
        accounting metadata. Fields we don't have data for are not omitted —
        the gateway does not use defaults or not ignore them.
        """
        partner = self.partner_id
        company_partner = self.company_id.partner_id

        # Split partner name into first/last name
        # Odoo stores full name in partner.name; try to split sensibly
        name_parts = (partner.name).strip().split(' ', 1)
        vorname = name_parts[0] if len(name_parts) > 1 else ''
        nachname = name_parts[1] if len(name_parts) > 1 else name_parts[0]

        # Prefer customer address; fallback to company address when missing.
        kunde_strasse = (partner.street or company_partner.street or '').strip()[:50]
        kunde_plz = (partner.zip or company_partner.zip or '').strip()[:6]
        kunde_ort = (partner.city or company_partner.city or '').strip()[:50]
        kunde_adresszusatz = (partner.street2 or company_partner.street2 or '').strip()[:75]

        today = fields.Date.today()
        due_date = self.invoice_ids.mapped('invoice_date_due') if self.invoice_ids else None
        # Use the latest due date among linked invoices, or in 1 month if none are set
        if due_date:
            due_date = max(d for d in due_date if d) or fields.Date.add(today, months=1)
        else:
            due_date = fields.Date.add(today, months=1)

        invoice_date = self.invoice_ids.mapped('invoice_date') if self.invoice_ids else None
        if invoice_date:
            invoice_date = max(d for d in invoice_date if d) or today
        else:
            invoice_date = today

        # noinspection DuplicatedCode
        ihv_data = {
            'haushaltsJahr': str(invoice_date.year),
            "haushaltsKennz": "000",
            "kapitel": "0000",
            "titel": "00000",
            "titelKennz": "0",
            "mahnSchluessel": "11",
            "schluesselKleinbetrag": "01",
            "schluesselVerzugszins": "0",
            "anrede": "",
            "anordnungsStellenNr": "0000000",
            "anordnungsStellenUnterNr": "0000000",
            "ebene1": "",
            "ebene2": "",
            "ebene3": "",
            "sonstAngabenZp": "",
            "budgetNr": "",
            "interneNotiz": "",
            "blzLastschrift": "",
            "kontoNrLastschrift": "",
            "feststeller": "Administrator",
            'kundeVorname': vorname,
            'kundeNachname': nachname,
            "kundeAnrede": "",
            "kundeTitel": "",
            "kundeStrasse": kunde_strasse,
            "kundeAdresszusatz": kunde_adresszusatz,
            "kundePlz": kunde_plz,
            "kundeOrt": kunde_ort,
            'betrag': str(self.amount),  # in euros
            'isoCode': 'DE',
            'verwendungszweck': ('Zahlung %s' % self.epsbayern_sanitized_ref)[:80],
            'faelligkeit': due_date.strftime('%d.%m.%Y'),
            "externAnordnungsBefugter": "",
            "immobiliennummer": "",
            "klrStatus": "N",
            "rechnungErforderlich": "N",
            "rechnungsart": "",
            "freieAnlage": "",
            "nachnameAnsprechpartner": "",
            "vornameAnsprechpartner": "",
            "anredeAnsprechpartner": "",
            "titelAnsprechpartner": "",
            "dienstbezeichnungAnsprechpartner": "",
            "telefonnebenstellennummerAnsprechpartner": "",
            "zimmernummerAnsprechpartner": "",
            "dienststellennummerAnsprechpartner": "",
            "dienststellenbereichAnsprechpartner": "",
            "dienststelleStandardforderung": "",
            "schluesselStandardforderung": "",
            "rechnungstext": "",
            "mwstBetrag": "",
            "mwstSatz": "",
            "mwstBetrag2": "",
            "mwstSatz2": "",
            "mwstBetrag3": "",
            "mwstSatz3": "",
        }

        return ihv_data

    def _epsbayern_build_hkr_data(self):
        return {
            "accountingKey": "000000000019",  # Buchungskennzeichen
            "settings": "NO_HKR_EXPORT"
        }

    def _epsbayern_build_cart(self):
        """Build the EPS Bayern cart payload grouped by VAT rate.

        One cart position per VAT rate, summing all line amounts at that rate.
        Sources (in priority): sale_order_ids > invoice_ids > self.amount.
        """
        _logger.debug("Building EPS Bayern cart for tx %s", self.reference)

        # Collect net/vat/gross per rate: {rate: {'net': int, 'vat': int, 'gross': int}}
        buckets = {}

        if self.sale_order_ids:
            for order in self.sale_order_ids:
                for line in order.order_line:
                    if line.display_type:
                        continue
                    rate = line.tax_id[0].amount if line.tax_id else 0.0
                    line_net = _to_cents(line.price_subtotal)
                    line_gross = _to_cents(line.price_total)
                    line_vat = line_gross - line_net
                    b = buckets.setdefault(rate, {'net': 0, 'vat': 0, 'gross': 0})
                    b['net'] += line_net
                    b['vat'] += line_vat
                    b['gross'] += line_gross

        elif self.invoice_ids:
            invoices = self.invoice_ids.filtered(
                lambda inv: inv.move_type == 'out_invoice'
            )
            for inv in invoices:
                for line in inv.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                    rate = line.tax_ids[0].amount if line.tax_ids else 0.0
                    line_net = _to_cents(line.price_subtotal)
                    line_gross = _to_cents(line.price_total)
                    line_vat = line_gross - line_net
                    b = buckets.setdefault(rate, {'net': 0, 'vat': 0, 'gross': 0})
                    b['net'] += line_net
                    b['vat'] += line_vat
                    b['gross'] += line_gross

        # Fallback: transaction has no linked sale orders or invoices (or they have
        # no product lines). Treat the full transaction amount as a single 0%-VAT
        # position. We are not able to get the tax rates etc. This should not happen in our use case,
        # but could happen somewhere else.
        # FIXME: Any way to get the tax rate of what is being paid?
        if not buckets:
            gross_cents = _to_cents(self.amount)
            buckets[0.0] = {'net': gross_cents, 'vat': 0, 'gross': gross_cents}
            _logger.warning("EPS Bayern: no line data for tx %s, using amount as single 0%% position", self.reference)

        # Build positions — one per VAT rate
        currency = self.currency_id.name or 'EUR'
        ref = self.epsbayern_sanitized_ref[:30]
        positions = []
        vat_positions = []
        total_net = 0
        total_gross = 0

        for pos_id, (rate, amounts) in enumerate(sorted(buckets.items()), start=1):
            positions.append(CartPosition(
                pos_id=pos_id,
                article_ref=ref,
                article_desc=ref,
                sum_net_amount=amounts['net'],
                vat=rate,
                vat_amount=amounts['vat'],
                gross_amount=amounts['gross'],
                currency=currency,
            ))
            vat_positions.append(VatPosition(
                pos_id=pos_id,
                vat=rate,
                vat_amount=amounts['vat'],
            ))
            total_net += amounts['net']
            total_gross += amounts['gross']

        cart = Cart(
            cart_ref=ref,
            total_net_amount=total_net,
            total_gross_amount=total_gross,
            currency=currency,
            positions=positions,
            vat_positions=vat_positions,
        )
        return cart.to_dict()

    # User came back. Find the transaction from notification/return data
    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != const.EPSBAYERN_PROVIDER_CODE or len(tx) == 1:  # Why len(tx) == 1?
            return tx

        reference = notification_data.get('reference')
        eps_txnid = notification_data.get('eps_txnid')  # on return from payment, it gives txnid in query param but
        # not crucial here since we have the reference to match
        if not reference:
            raise ValidationError(
                "EPS Bayern: " + _("Received data with missing reference.")
            )

        tx = self.search([
            ('epsbayern_sanitized_ref', '=', reference),
            ('provider_code', '=', const.EPSBAYERN_PROVIDER_CODE),
        ])
        if not tx:
            raise ValidationError(
                "EPS Bayern: " + _("No transaction found matching reference %s.", reference)
            )

        if eps_txnid:
            try:
                returned_id = eps_txnid
                stored_id = tx.provider_reference
            except (ValueError, TypeError):
                raise ValidationError(
                    "EPS Bayern: " + _("Invalid txnId format. Ref: %s, txnId: %s", reference, eps_txnid)
                )
            if returned_id != stored_id:
                _logger.error(
                    'EPS Bayern: returned txnId does NOT match stored provider_reference. '
                    'Ref: %s, returned txnid: %s, db provider reference: %s', reference, eps_txnid,
                    tx.provider_reference)
                raise ValidationError(
                    "EPS Bayern: " + _(
                        "Returned txnId does not match stored reference. Ref: %s, txnId: %s",
                        reference, eps_txnid)
                )

        return tx

    # Process notification → check status → auto-capture → update state ---
    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != const.EPSBAYERN_PROVIDER_CODE:
            return

        if not notification_data:
            raise ValidationError(
                "EPS Bayern: " + _("Received empty notification data for reference %s.", self.reference)
            )

        if not self.provider_reference:
            raise ValidationError(
                "EPS Bayern: " + _("Transaction %s has no provider reference (txnId).", self.reference)
            )

        txn_id = self.provider_reference

        # Query current transaction status
        status_response = self.provider_id._gateway_make_request(
            const.GATEWAY_API_ENDPOINTS['get_txn_status'],
            payload={'txnId': txn_id}
        )

        status_data = status_response.get('txnStatusResponseData', {})
        return_status = status_data.get('returnStatus', {})
        if not _successfull_return_status(return_status):
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

            if not _successfull_return_status(return_status):
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

    def _send_refund_request(self, amount_to_refund=None):
        """
            Prepare and send a refund request.
            Reverses the invoice/s after successfull refund so the refund has proper accounting documents.
            The outbound payment will reconcile against the credit note.
                Two types of Stornierungen:
                1. Cancel (storno) VOID the entire transaction - This is free of charge, but only possible before the payment
                register is finalized
                2. Return (reverse) the entire transaction - This costs a fee
        """
        refund_tx = super()._send_refund_request(amount_to_refund=amount_to_refund)
        if self.provider_code != const.EPSBAYERN_PROVIDER_CODE:
            return refund_tx

        if not self.provider_reference:
            raise ValidationError(
                "EPS Bayern: " + _("Cannot refund: source transaction has no provider reference.")
            )

        txn_id = self.provider_reference

        _logger.info(
            "EPS Bayern refund for reference %s, source txnId=%s",
            self.reference, txn_id
        )

        _logger.info(
            "EPS Bayern attempting CANCEL (storno) for tx %s, source txnId=%s",
            self.reference, txn_id
        )

        # First try to cancel it
        refund_method = None
        try:
            cancel_response = self.provider_id._gateway_make_request(
                const.GATEWAY_API_ENDPOINTS['execute'],
                payload={'command': 'VOID', 'txnId': txn_id}
            )
            cancel_exec_data = cancel_response.get('executeResponseData', {})
            cancel_base_response = cancel_exec_data.get('responseData', {}).get('baseResponseData', {})
            cancel_return_status = cancel_base_response.get('returnStatus', {})

            if not _successfull_return_status(cancel_return_status):
                _logger.info("EPS Bayern CANCEL not successful (returnCode != 0), falling back to RETURN")
                raise ValidationError("CANCEL failed")

            _logger.info("EPS Bayern CANCEL successful for %s", self.reference)
            base_response = cancel_base_response
            refund_method = 'CANCEL'

        except ValidationError:
            # Cannot cancel, attempt return
            _logger.info(
                "EPS Bayern CANCEL failed/rejected. Attempting RETURN (reverse) for %s",
                self.reference
            )
            refund_response = self.provider_id._gateway_make_request(
                const.GATEWAY_API_ENDPOINTS['execute'],
                payload={'command': 'RETURN', 'txnId': txn_id}
            )

            exec_data = refund_response.get('executeResponseData', {})
            base_response = exec_data.get('responseData', {}).get('baseResponseData', {})
            return_status = base_response.get('returnStatus', {})

            if not _successfull_return_status(return_status):
                # Throw, so further the refund can not be processed
                raise ValidationError(
                    "EPS Bayern: " + _(
                        "Refund (RETURN) also failed: %s", pprint.pformat(refund_response)
                    )
                )
            refund_method = 'RETURN'

        refund_txn_id = str(base_response.get('txnId', txn_id))

        refund_tx.provider_reference = refund_txn_id
        refund_tx.epsbayern_sanitized_ref = self.epsbayern_sanitized_ref

        # Create a credit note (reversal) for the source invoices so the refund
        # has proper accounting documents. The outbound payment will reconcile
        # against the credit note.
        # NOTE: In this point even tough we do not depend on "account" package, if source invoices are present
        # the account module should be already installed, and we do reversal on them
        source_invoices = self.invoice_ids.filtered(
            lambda inv: inv.state == 'posted' and inv.move_type == 'out_invoice'
        ) if self.invoice_ids else None

        if source_invoices:
            reversal_wizard = self.env['account.move.reversal'].with_context(
                active_model='account.move',
                active_ids=source_invoices.ids,
            ).create({
                'journal_id': source_invoices[0].journal_id.id,
            })
            reversal_wizard.refund_moves()
            credit_notes = reversal_wizard.new_move_ids
            if credit_notes:
                credit_notes.action_post()
                refund_tx.invoice_ids = credit_notes
                _logger.info(
                    "EPS Bayern: created credit note(s) %s for refund tx %s",
                    credit_notes.mapped('name'), refund_tx.reference
                )

        refund_tx._set_done()

        # Trigger post-processing immediately since the gateway response is synchronous.
        # This creates the account.payment (outbound) and reconciles against the credit note.
        refund_tx._post_process()

        return refund_tx

    # Cron: check stale pending transactions
    def _cron_epsbayern_check_stale_transactions(self):
        """Check pending EPS Bayern transactions and update their status."""
        timeout = const.STALE_TRANSACTION_TIMEOUT_HOURS
        deadline = fields.Datetime.subtract(fields.Datetime.now(), hours=timeout)
        stale_txs = self.search([
            ('provider_code', '=', const.EPSBAYERN_PROVIDER_CODE),
            ('state', 'in', ('draft', 'pending')),
            ('provider_reference', '!=', False),
            ('create_date', '<', deadline),
        ])

        _logger.info(
            "EPS Bayern cron: checking %d stale transactions (older than %d hours)",
            len(stale_txs), timeout
        )

        for tx in stale_txs:
            try:
                txn_id = tx.provider_reference
                status_response = tx.provider_id._gateway_make_request(
                    const.GATEWAY_API_ENDPOINTS['get_txn_status'],
                    payload={'txnId': txn_id}
                )
                status_data = status_response.get('txnStatusResponseData', {})
                return_status = status_data.get('returnStatus', {})

                if not _successfull_return_status(return_status):
                    _logger.error(
                        "EPS Bayern cron: status check failed for reference %s (txnId=%s): %s",
                        tx.reference, txn_id, pprint.pformat(status_response.json())
                    )
                    continue

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
                        "EPS Bayern cron: aborting stale reference %s (txnId=%s, status=%s)",
                        tx.reference, txn_id, status_desc
                    )
                    try:
                        tx.provider_id._gateway_make_request(
                            const.GATEWAY_API_ENDPOINTS['abort_txn'],
                            payload={'txnId': txn_id}
                        )
                    except ValidationError:
                        _logger.exception(
                            "EPS Bayern cron: abort failed for reference %s, txn id: %s", tx.reference,
                            txn_id
                        )
                    tx._set_canceled(
                        state_message=_("Transaction timed out and was aborted.")
                    )
            except Exception:
                _logger.exception(
                    "EPS Bayern cron: error processing stale reference %s, txn id:", tx.reference, tx.provider_reference
                )

    # Internal action: fetch detailed transaction status
    def action_fetch_txn_status_detail(self):
        """Fetch the detailed transaction status from the EPS Bayern gateway and show in a wizard."""
        self.ensure_one()

        if self.provider_code != const.EPSBAYERN_PROVIDER_CODE:
            raise ValidationError(_("This action is only available for EPS Bayern transactions."))

        if not self.provider_reference:
            raise ValidationError(
                _("Cannot fetch status: this transaction has no provider reference (txnId).")
            )

        txn_id = self.provider_reference

        response = self.provider_id._gateway_make_request(
            const.GATEWAY_API_ENDPOINTS['get_txn_status_detail'],
            payload={'txnId': txn_id}
        )

        _logger.info(
            "EPS Bayern: fetched detailed status for tx %s (txnId=%s)",
            self.reference, txn_id
        )

        wizard = self.env['payment.epsbayern.txn.status.detail.wizard'].create({
            'transaction_id': self.id,
            'status_detail_json': json.dumps(response, indent=2, ensure_ascii=False),
        })

        return {
            'name': _('Transaction Status Detail — %s', self.reference),
            'type': 'ir.actions.act_window',
            'res_model': 'payment.epsbayern.txn.status.detail.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
