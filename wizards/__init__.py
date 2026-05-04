from odoo import fields, models


class PaymentEpsbayernTxnStatusDetailWizard(models.TransientModel):
    _name = 'payment.epsbayern.txn.status.detail.wizard'
    _description = 'EPS Bayern Transaction Status Detail'

    transaction_id = fields.Many2one('payment.transaction', string="Transaction", readonly=True)
    status_detail_json = fields.Text(string="Status Detail (JSON)", readonly=True)
