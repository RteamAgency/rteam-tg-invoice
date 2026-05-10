# rteam-tg-invoice

One-tap **Vendor Bill approvals in Telegram** for Odoo 19. CFO sign-off
before money leaves the company, from a phone, anywhere — no VPN, no
Odoo login, no inbox dig.

## What it does

When a Vendor Bill (`account.move` with `move_type='in_invoice'`) at or
above the configured threshold is posted, the move is held in draft and
a Telegram message with inline **Approve / Reject / View in Odoo**
buttons is delivered to the configured approver. One tap and the bill
posts; the chatter records who approved and when.

Customer Invoices, Vendor Refunds and Customer Refunds are NOT gated —
those flows are usually less risk-sensitive in finance approval policies.

## Dependency

This module sits on top of [`rteam_tg_auth`](https://github.com/RteamAgency/rteam-tg-auth) —
the source-agnostic Telegram approval ledger + 2FA core. Install
`rteam_tg_auth` first (or alongside, Odoo will resolve the order) and
bind your approver(s) to Telegram via My Preferences before the gate
can fire.

## Branches

- `main` — primary working branch.
- `19.0` — exact mirror of `main`, the branch apps.odoo.com Scan reads from.

Per Rteam Odoo Apps convention every push to `main` is mirrored to `19.0`.
17.0 / 18.0 backports follow on demand.

## License

LGPL-3.

## Maintainer

Rteam, alex@rteam.top, https://rteam.agency
