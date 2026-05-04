/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc, RPCError, ConnectionLostError } from '@web/core/network/rpc';

/**
 * Override the default payment post-processing widget to stop auto-redirecting
 * on final states. Instead, show the final status and a "Continue" button so
 * the user can see whether the payment succeeded or failed.
 */
publicWidget.registry.PaymentPostProcessing = publicWidget.Widget.extend({
    selector: 'div[name="o_payment_status"]',

    timeout: 0,
    pollCount: 0,

    async start() {
        this._poll();
        return this._super.apply(this, arguments);
    },

    _poll() {
        this._updateTimeout();
        setTimeout(() => {
            const self = this;
            rpc('/payment/status/poll', {
                'csrf_token': odoo.csrf_token,
            }).then(postProcessingValues => {
                const { state, landing_route } = postProcessingValues;

                if (self._getFinalStates().has(state)) {
                    // Don't redirect — show the result and a continue button
                    self._showFinalState(state, landing_route);
                } else {
                    self._poll();
                }
            }).catch(error => {
                const isRetryError = error instanceof RPCError && error.data.message === 'retry';
                const isConnectionLostError = error instanceof ConnectionLostError;
                if (isRetryError || isConnectionLostError) {
                    self._poll();
                }
                if (!isRetryError) {
                    throw error;
                }
            });
        }, this.timeout);
    },

    _getFinalStates() {
        return new Set(['authorized', 'done', 'cancel', 'error']);
    },

    _showFinalState(state, landingRoute) {
        const statusEl = this.el.querySelector('.o_payment_status_content');
        if (!statusEl) return;

        // Sanitize landingRoute to prevent open redirect / XSS
        const safeLandingRoute = (landingRoute && landingRoute.startsWith('/'))
            ? landingRoute : '/';

        let alertClass, icon, title, message;

        if (state === 'done' || state === 'authorized') {
            alertClass = 'alert-success';
            icon = 'fa-check-circle';
            title = 'Zahlung erfolgreich';
            message = 'Ihre Zahlung wurde erfolgreich verarbeitet.';
        } else if (state === 'cancel') {
            alertClass = 'alert-warning';
            icon = 'fa-exclamation-circle';
            title = 'Zahlung abgebrochen';
            message = 'Die Zahlung wurde abgebrochen.';
        } else {
            alertClass = 'alert-danger';
            icon = 'fa-times-circle';
            title = 'Zahlung fehlgeschlagen';
            message = 'Bei der Zahlung ist ein Fehler aufgetreten. Bitte versuchen Sie es erneut.';
        }

        statusEl.innerHTML = `
            <div class="alert ${alertClass} d-flex align-items-center mb-3" role="alert">
                <i class="fa ${icon} fa-2x me-3"></i>
                <div>
                    <strong>${title}</strong><br/>
                    ${message}
                </div>
            </div>
            <div class="text-center">
                <a href="${safeLandingRoute}" class="btn btn-primary">
                    Weiter <i class="fa fa-arrow-right ms-1"></i>
                </a>
            </div>
        `;
    },

    _updateTimeout() {
        if (this.pollCount >= 1 && this.pollCount < 10) {
            this.timeout = 3000;
        }
        if (this.pollCount >= 10 && this.pollCount < 20) {
            this.timeout = 10000;
        } else if (this.pollCount >= 20) {
            this.timeout = 30000;
        }
        this.pollCount++;
    },
});

export default publicWidget.registry.PaymentPostProcessing;
