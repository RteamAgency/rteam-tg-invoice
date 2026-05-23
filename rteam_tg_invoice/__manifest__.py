{
    "name": "Rteam Telegram Approvals: Vendor Bills",
    "version": "19.0.1.1.0",
    "category": "Accounting",
    "summary": "One-tap Vendor Bill approvals in Telegram. CFO sign-off from a phone before money leaves the company.",
    "description": """
Rteam Telegram Approvals: Vendor Bills
======================================

Stop chasing your CFO with "please validate vendor bill BILL/2026/0123".
When a Vendor Bill above the configured threshold is posted, an inline
Telegram message goes straight to the approver's phone with three
buttons: Approve, Reject, View in Odoo. One tap and the bill posts in
Odoo, the chatter records who approved and when. No VPN, no Odoo login,
no inbox dig.

Scope
-----
This module gates Vendor Bills only (``account.move`` with
``move_type='in_invoice'``). Customer Invoices, Vendor Refunds and
Customer Refunds post normally without a Telegram detour, since those
flows are usually less risk-sensitive in finance approval policies.

How it works
------------
1. Install this module on top of ``rteam_tg_auth``.
2. The approver completes Bind Telegram once in their Odoo Preferences
   (60 seconds via the deep link the bot sends them).
3. Set Settings -> Telegram -> Vendor Bill Approvals: a Threshold (the
   amount above which approval is required) and a Default approver.
4. From now on, when a Vendor Bill at or above the threshold is posted,
   the move is held in draft state and a Telegram message with inline
   Approve / Reject buttons is delivered to the configured approver.
   Their tap flips the move to posted or leaves it in draft, and posts
   a chatter note linking the action back to the approver and the time.

Security
--------
Each inline button carries an HMAC-signed callback payload. An attacker
who learns a request id alone cannot forge a tap without the
per-instance webhook secret. Telegram messages and webhook callbacks
share the same path-and-header secret; the bot token never leaves your
database.

Reliability
-----------
* Stale requests (24h default) auto-expire on a 30-minute cron, with a
  chatter note on the source bill.
* Approver opens the same bill in Odoo? The header shows a "View
  Telegram approval" button so they can see exactly which TG message is
  in flight.
* Re-posting a bill with an open request raises a clear error rather
  than spawning a duplicate.
* Self-approve is blocked: requester == approver = no Telegram detour,
  the move posts normally, and the chatter explains why.

Family
------
Part of the Rteam Telegram Approvals family on top of the same
``rteam_tg_auth`` ledger. Sibling modules:

* ``rteam_tg_purchase`` -- Purchase Order approvals
* ``rteam_tg_timeoff`` -- Time Off approvals (planned)
* ``rteam_tg_expenses`` -- Expense Report approvals (planned)

Building your own integration is one method on the source model:
``on_rteam_tg_approval_resolved(request, new_state)``.
""",
    "author": "Rteam",
    "maintainer": "Rteam",
    "website": "https://rteam.agency",
    "support": "alex@rteam.top",
    "license": "LGPL-3",
    "depends": ["rteam_tg_auth", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter_data.xml",
        "views/account_move_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "images": [
        "static/description/banner.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
