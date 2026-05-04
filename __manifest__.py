{
    'name': 'Payment Provider: ePayServiceBayern',
    'version': '0.1',
    'category': 'Accounting/Payment Providers',
    'author': 'MINcom Smart Solutions GmbH',
    'sequence': 350,
    'summary': "ePayServiceBayern Zahlungsabwickler (über die Hochschule München)",
    'description': "ePayServiceBayern",
    'depends': ['payment'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_epsbayern_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'wizards/txn_status_detail_wizard_views.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
        'data/payment_cron_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_epsbayern/static/src/js/post_processing.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'license': 'LGPL-3',
}