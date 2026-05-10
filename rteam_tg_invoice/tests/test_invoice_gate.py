"""Integration tests for account.move (Vendor Bill) Telegram-gated post flow."""

from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestInvoiceGate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        params.set_param("rteam_tg_auth.webhook_secret", "deadbeef" * 4)
        params.set_param("rteam_tg_auth.bot_username", "test_bot")

        cls.requester = cls.env["res.users"].create(
            {"name": "Bookkeeper Joe", "login": "bookkeeper_joe_inv"}
        )
        cls.approver = cls.env["res.users"].create({"name": "CFO Anna", "login": "cfo_anna_inv"})
        cls.env["rteam.tg.binding"].create(
            {
                "user_id": cls.approver.id,
                "state": "active",
                "chat_id": "555555",
                "bound_at": fields.Datetime.now(),
            }
        )
        cls.vendor = cls.env["res.partner"].create({"name": "Vendor X", "supplier_rank": 1})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Service",
                "type": "service",
                "purchase_ok": True,
                "list_price": 100.0,
                "standard_price": 80.0,
            }
        )

    def _bill(self, qty, price, requester=None, move_type="in_invoice"):
        # invoice_user_id only exists on customer/vendor invoices, not entries.
        vals = {
            "move_type": move_type,
            "partner_id": self.vendor.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": self.product.id,
                        "quantity": qty,
                        "price_unit": price,
                    },
                )
            ],
        }
        if move_type in ("in_invoice", "in_refund", "out_invoice", "out_refund"):
            vals["invoice_user_id"] = (requester or self.requester).id
        return self.env["account.move"].create(vals)

    def _set_gate(self, threshold, approver_id):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("rteam_tg_invoice.threshold", str(threshold))
        params.set_param("rteam_tg_invoice.approver_user_id", str(approver_id))

    def _patched_tg(self):
        return patch.multiple(
            "odoo.addons.rteam_tg_auth.models.rteam_tg_approval_request",
            send_message_with_buttons=MagicMock(return_value={"message_id": 100}),
            answer_callback_query=MagicMock(return_value=True),
            edit_message_reply_markup=MagicMock(return_value=True),
        )

    # --------------------------------------------------------------- pass-through

    def test_below_threshold_posts_normally(self):
        self._set_gate(threshold=10000, approver_id=self.approver.id)
        bill = self._bill(qty=1, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        self.assertEqual(bill.state, "posted")
        self.assertEqual(
            self.env["rteam.tg.approval.request"].search_count(
                [("source_model", "=", "account.move"), ("source_id", "=", bill.id)]
            ),
            0,
        )

    def test_no_approver_configured_passes_through(self):
        self._set_gate(threshold=10, approver_id=0)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        self.assertEqual(bill.state, "posted")

    def test_self_approve_passes_through(self):
        self._set_gate(threshold=10, approver_id=self.requester.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        self.assertEqual(bill.state, "posted")

    def test_self_approve_posts_explanation_to_chatter(self):
        self._set_gate(threshold=10, approver_id=self.requester.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        msgs = self.env["mail.message"].search(
            [("model", "=", "account.move"), ("res_id", "=", bill.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertIn("self-approval", bodies)

    def test_below_threshold_posts_no_skip_explanation(self):
        self._set_gate(threshold=10000, approver_id=self.approver.id)
        bill = self._bill(qty=1, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        msgs = self.env["mail.message"].search(
            [("model", "=", "account.move"), ("res_id", "=", bill.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertNotIn("self-approval", bodies)
        self.assertNotIn("No Telegram approval", bodies)

    # --------------------------------------------------------------- scope guard

    def test_customer_invoice_never_gated(self):
        # out_invoice should always pass through, even if amount > threshold
        # and approver != requester. This is the central scope contract.
        self._set_gate(threshold=10, approver_id=self.approver.id)
        inv = self._bill(qty=10, price=100.0, move_type="out_invoice")
        with self._patched_tg():
            inv.with_user(self.requester).action_post()
        self.assertEqual(inv.state, "posted")
        self.assertEqual(
            self.env["rteam.tg.approval.request"].search_count(
                [("source_model", "=", "account.move"), ("source_id", "=", inv.id)]
            ),
            0,
        )

    def test_vendor_refund_never_gated(self):
        self._set_gate(threshold=10, approver_id=self.approver.id)
        refund = self._bill(qty=10, price=100.0, move_type="in_refund")
        with self._patched_tg():
            refund.with_user(self.requester).action_post()
        self.assertEqual(refund.state, "posted")

    # --------------------------------------------------------------- gated

    def test_above_threshold_creates_pending_request_and_holds_state(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        self.assertEqual(bill.state, "draft", "Bill must be held in draft until approval")
        req = self.env["rteam.tg.approval.request"].search(
            [("source_model", "=", "account.move"), ("source_id", "=", bill.id)],
            order="create_date desc",
            limit=1,
        )
        self.assertTrue(req)
        self.assertEqual(req.state, "pending")
        self.assertEqual(req.approver_user_id, self.approver)
        self.assertEqual(req.requester_user_id, self.requester)

    def test_re_post_with_pending_raises(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        with self._patched_tg():
            with self.assertRaises(UserError):
                bill.with_user(self.requester).action_post()

    def test_approve_callback_posts_bill(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        req = self.env["rteam.tg.approval.request"].search(
            [("source_model", "=", "account.move"), ("source_id", "=", bill.id)],
            limit=1,
        )
        with self._patched_tg():
            ok = req._resolve("y", callback_query_id="cbq", actor_chat_id="555555")
        self.assertTrue(ok)
        self.assertEqual(bill.state, "posted", "Approve must trigger super().action_post")
        msgs = self.env["mail.message"].search(
            [("model", "=", "account.move"), ("res_id", "=", bill.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertIn("Approved via Telegram", bodies)

    def test_reject_callback_keeps_bill_in_draft(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        req = self.env["rteam.tg.approval.request"].search(
            [("source_model", "=", "account.move"), ("source_id", "=", bill.id)],
            limit=1,
        )
        with self._patched_tg():
            ok = req._resolve("n", callback_query_id="cbq", actor_chat_id="555555")
        self.assertTrue(ok)
        self.assertEqual(bill.state, "draft", "Reject must NOT post")

    def test_pending_request_reflected_on_bill_form(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        bill = self._bill(qty=10, price=100.0)
        with self._patched_tg():
            bill.with_user(self.requester).action_post()
        self.assertTrue(bill.rteam_tg_has_pending)
        self.assertTrue(bill.rteam_tg_pending_request_id)
