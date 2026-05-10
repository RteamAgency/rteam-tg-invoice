"""Hook account.move.action_post to gate large Vendor Bills through Telegram approval."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

VENDOR_BILL = "in_invoice"


class AccountMove(models.Model):
    _inherit = "account.move"

    rteam_tg_pending_request_id = fields.Many2one(
        "rteam.tg.approval.request",
        compute="_compute_pending_request",
        store=False,
    )
    rteam_tg_has_pending = fields.Boolean(
        compute="_compute_pending_request",
        store=False,
    )

    @api.depends("amount_total", "state", "move_type")
    def _compute_pending_request(self):
        Approval = self.env["rteam.tg.approval.request"].sudo()
        for move in self:
            req = Approval.search(
                [
                    ("source_model", "=", "account.move"),
                    ("source_id", "=", move.id),
                    ("state", "=", "pending"),
                ],
                order="create_date desc",
                limit=1,
            )
            move.rteam_tg_pending_request_id = req.id or False
            move.rteam_tg_has_pending = bool(req)

    # ---------------------------------------------------------------- helpers

    @api.model
    def _rteam_tg_invoice_settings(self):
        params = self.env["ir.config_parameter"].sudo()
        try:
            threshold = float(params.get_param("rteam_tg_invoice.threshold", "0") or "0")
        except (TypeError, ValueError):
            threshold = 0.0
        approver_id = params.get_param("rteam_tg_invoice.approver_user_id")
        try:
            approver_id = int(approver_id) if approver_id else 0
        except (TypeError, ValueError):
            approver_id = 0
        approver = self.env["res.users"].sudo().browse(approver_id) if approver_id else None
        return threshold, approver

    def _rteam_tg_should_gate(self):
        """Return the approver if this move must be gated; falsy otherwise.

        Only Vendor Bills (move_type=in_invoice) are gated. Customer
        Invoices, Vendor/Customer Refunds and journal entries fall
        through to normal posting.
        """
        self.ensure_one()
        if self.move_type != VENDOR_BILL:
            return False
        threshold, approver = self._rteam_tg_invoice_settings()
        if not approver or not approver.exists():
            return False
        if approver.id == self.env.user.id:
            # Don't ask people to approve their own bills.
            return False
        if self.amount_total < threshold:
            return False
        return approver

    def _rteam_tg_gate_skip_reason(self):
        """Why was a Vendor Bill candidate NOT gated? Returns a string only
        when the chatter benefits from explanation: the move was a real
        gating candidate (vendor bill, amount >= threshold, approver set)
        but the gate self-skipped. Otherwise returns None.

        Same UX rationale as rteam_tg_purchase: silent passthrough on
        self-approve confused testers, so we now narrate.
        """
        self.ensure_one()
        if self.move_type != VENDOR_BILL:
            return None
        threshold, approver = self._rteam_tg_invoice_settings()
        if not approver or not approver.exists():
            return None
        if self.amount_total < threshold:
            return None
        if approver.id == self.env.user.id:
            return _(
                "No Telegram approval was requested: you are configured as "
                "the approver, and the gate skips self-approvals. To test "
                "the flow, post the bill as a different user, or change the "
                "approver in Settings -> Telegram -> Vendor Bill Approvals."
            )
        return None

    # ---------------------------------------------------------------- override

    def action_post(self):
        """Intercept post: if the bill is a Vendor Bill at or above the
        threshold and an approver is configured, fire a Telegram approval
        and stop here.

        The original ``action_post`` runs from
        ``on_rteam_tg_approval_resolved`` once the approver taps Approve
        in Telegram.
        """
        if self.env.context.get("rteam_tg_skip_gate"):
            return super().action_post()

        gated_moves = self.env["account.move"]
        passthrough_moves = self.env["account.move"]
        skip_reasons = {}  # move.id -> reason str
        for move in self:
            approver = move._rteam_tg_should_gate()
            if approver:
                gated_moves |= move
            else:
                passthrough_moves |= move
                reason = move._rteam_tg_gate_skip_reason()
                if reason:
                    skip_reasons[move.id] = reason

        result = super(AccountMove, passthrough_moves).action_post() if passthrough_moves else True

        for move in passthrough_moves:
            reason = skip_reasons.get(move.id)
            if reason:
                move.message_post(body=reason, subtype_xmlid="mail.mt_note")

        for move in gated_moves:
            existing = move.rteam_tg_pending_request_id
            if existing:
                raise UserError(
                    _(
                        "%(bill)s already has a pending approval request in Telegram. "
                        "Wait for it to be answered, or cancel it from the Telegram "
                        "Approvals menu."
                    )
                    % {"bill": move.display_name}
                )
            approver = move._rteam_tg_should_gate()
            summary = move._rteam_tg_summary()
            self.env["rteam.tg.approval.request"].sudo().request_approval(
                source_record=move,
                approver_user=approver,
                summary=summary,
                requester_user=self.env.user,
            )
            move.message_post(
                body=_(
                    "Telegram approval request sent to %(approver)s. "
                    "The bill will be posted when they tap Approve."
                )
                % {"approver": approver.display_name},
                subtype_xmlid="mail.mt_note",
            )

        if gated_moves and not passthrough_moves:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "info",
                    "sticky": False,
                    "title": _("Awaiting Telegram approval"),
                    "message": _(
                        "Approval request delivered. The bill stays in its current state until the approver taps in Telegram."
                    ),
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return result

    def _rteam_tg_summary(self):
        self.ensure_one()
        currency = self.currency_id.name or ""
        partner = self.partner_id.display_name or "-"
        line_count = len(self.invoice_line_ids)
        return (
            f"Vendor: {partner}\n"
            f"Total: {self.amount_total:,.2f} {currency}\n"
            f"Lines: {line_count}\n"
            f"Reference: {self.ref or '-'}"
        )

    # ---------------------------------------------------------------- callback

    def on_rteam_tg_approval_resolved(self, request, new_state):
        """Source-model hook called by ``rteam.tg.approval.request._resolve``.

        ``new_state`` is one of approved / rejected / expired / cancelled.
        """
        self.ensure_one()
        if new_state == "approved":
            try:
                # Bypass the gate to avoid a recursive approval loop.
                self.with_context(rteam_tg_skip_gate=True).action_post()
            except Exception as e:  # noqa: BLE001
                _logger.exception("rteam_tg_invoice: action_post after approve failed")
                self.message_post(
                    body=_("Telegram approval came back APPROVED but auto-post failed: %s") % e,
                    subtype_xmlid="mail.mt_note",
                )
                return
            self.message_post(
                body=_("Approved via Telegram by %(approver)s. Vendor bill posted.")
                % {"approver": request.approver_user_id.display_name},
                subtype_xmlid="mail.mt_note",
            )
        elif new_state == "rejected":
            self.message_post(
                body=_("Rejected via Telegram by %(approver)s. Bill stays in %(state)s.")
                % {
                    "approver": request.approver_user_id.display_name,
                    "state": self.state,
                },
                subtype_xmlid="mail.mt_note",
            )
        elif new_state == "expired":
            self.message_post(
                body=_(
                    "Telegram approval request expired without an answer. "
                    "Re-post the bill to send a new request."
                ),
                subtype_xmlid="mail.mt_note",
            )

    # ---------------------------------------------------------------- view actions

    def rteam_tg_open_pending_request(self):
        self.ensure_one()
        if not self.rteam_tg_pending_request_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "rteam.tg.approval.request",
            "res_id": self.rteam_tg_pending_request_id.id,
            "view_mode": "form",
            "target": "current",
        }
