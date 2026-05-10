"""Per-company settings for Telegram-gated vendor bill approvals."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    rteam_tg_invoice_threshold = fields.Float(
        string="Approval threshold",
        config_parameter="rteam_tg_invoice.threshold",
        default=0.0,
        help=(
            "Vendor bills with a Total amount equal to or above this number "
            "trigger a Telegram approval request when posted. Below this "
            "threshold, the bill posts normally. Set to 0 to gate every bill "
            "(not recommended; high noise)."
        ),
    )
    rteam_tg_invoice_approver_id = fields.Many2one(
        "res.users",
        string="Default approver",
        config_parameter="rteam_tg_invoice.approver_user_id",
        help=(
            "Whoever is named here will receive the Telegram approval request. "
            "They must already have completed Bind Telegram in their Preferences."
        ),
    )
