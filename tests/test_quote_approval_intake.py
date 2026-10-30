import unittest

import main


class QuoteApprovalIntakeTests(unittest.TestCase):
    def test_normalizes_nested_approved_quote(self):
        result = main.normalize_revio_quote({
            "quoteId": 81234,
            "description": "Webex Calling for 42 users",
            "status": {"name": "Approved"},
            "customer": {"id": 1996, "name": "Test Customer"},
            "assignee": {"displayName": "Matthew Petrusha"},
            "approvedAt": "2026-10-30T13:45:00Z",
            "totalAmount": 2499.50,
        })

        self.assertEqual(result["quote_id"], "81234")
        self.assertTrue(result["is_approved"])
        self.assertEqual(result["customer_id"], "1996")
        self.assertEqual(result["customer_name"], "Test Customer")
        self.assertEqual(result["sales_owner"], "Matt")
        self.assertEqual(result["quote_name"], "Webex Calling for 42 users")

    def test_pending_approval_is_not_treated_as_approved(self):
        result = main.normalize_revio_quote({
            "id": "quote-1",
            "statusName": "Pending Approval",
        })

        self.assertFalse(result["is_approved"])

    def test_explicit_approved_flag_is_supported(self):
        result = main.normalize_revio_quote({
            "quote_id": "quote-2",
            "isApproved": True,
            "customerName": "ABC Company",
        })

        self.assertTrue(result["is_approved"])

    def test_intake_body_contains_review_context(self):
        body = main.revio_quote_intake_body({
            "quote_id": "81234",
            "customer_name": "ABC Company",
            "customer_id": "1996",
            "quote_name": "Webex Calling",
            "status_name": "Approved",
            "sales_owner": "Jack",
            "amount": "1500.00",
            "approved_at": None,
        })

        self.assertIn("Customer: ABC Company", body)
        self.assertIn("Quote ID: 81234", body)
        self.assertIn("Sales Owner: Jack", body)
        self.assertIn("Quote Total: 1500.00", body)


class QuoteApprovalSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main.Base.metadata.create_all(bind=main.engine)
        db = main.SessionLocal()
        try:
            db.query(main.QuoteApprovalState).delete()
            db.query(main.IntegrationSyncState).delete()
            db.query(main.IntakeEmail).filter(
                main.IntakeEmail.message_id.like("revio-psa-quote:%")
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    async def test_baselines_then_imports_approval_once(self):
        current_status = {"name": "Open"}

        async def fake_request(method, path, **kwargs):
            return {"data": [{
                "quoteId": 90001,
                "description": "Webex Calling deployment",
                "status": current_status.copy(),
                "customer": {"id": 1996, "name": "Test Customer"},
                "owner": {"name": "Jack Harris"},
            }]}

        original_request = main.revio_psa_api_request
        original_configured = main.revio_configured
        main.revio_psa_api_request = fake_request
        main.revio_configured = lambda: True
        try:
            baseline = await main.sync_revio_quote_approvals()
            self.assertEqual(baseline["imported"], 0)
            self.assertEqual(baseline["baselined"], 1)

            current_status["name"] = "Approved"
            approved = await main.sync_revio_quote_approvals()
            self.assertEqual(approved["imported"], 1)

            repeated = await main.sync_revio_quote_approvals()
            self.assertEqual(repeated["imported"], 0)

            db = main.SessionLocal()
            try:
                intake = db.query(main.IntakeEmail).filter_by(
                    message_id="revio-psa-quote:90001"
                ).one()
                self.assertEqual(intake.customer_id, "1996")
                self.assertEqual(intake.customer_name, "Test Customer")
                self.assertEqual(intake.sales_owner, "Jack")
            finally:
                db.close()
        finally:
            main.revio_psa_api_request = original_request
            main.revio_configured = original_configured


if __name__ == "__main__":
    unittest.main()
