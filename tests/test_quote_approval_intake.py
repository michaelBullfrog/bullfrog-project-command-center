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

    def test_scalar_status_is_supported(self):
        result = main.normalize_revio_quote({
            "quoteId": 12,
            "status": "Approved",
        })

        self.assertTrue(result["is_approved"])
        self.assertEqual(result["status_name"], "Approved")

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

    async def test_fetches_all_reported_quote_pages(self):
        async def fake_request(method, path, **kwargs):
            page = kwargs["params"]["page"]
            if page == 1:
                items = [{"quoteId": value, "status": "Open"} for value in range(1, 101)]
            else:
                items = [{"quoteId": 101, "status": "Approved"}]
            return {"data": {"items": items, "totalCount": 101}}

        original_request = main.revio_psa_api_request
        main.revio_psa_api_request = fake_request
        try:
            records, pages = await main.fetch_revio_quotes()
            self.assertEqual(len(records), 101)
            self.assertEqual(pages, 2)
        finally:
            main.revio_psa_api_request = original_request

    async def test_does_not_import_old_approved_quotes_discovered_by_pagination(self):
        async def fake_request(method, path, **kwargs):
            return {"data": [{
                "quoteId": 42,
                "status": "Approved",
                "createdDate": "2020-01-01T12:00:00Z",
            }]}

        db = main.SessionLocal()
        try:
            db.add(main.IntegrationSyncState(
                key=main.REVIO_QUOTE_BASELINE_KEY,
                value='{"created_at":"2026-10-30T12:00:00"}',
            ))
            db.commit()
        finally:
            db.close()

        original_request = main.revio_psa_api_request
        original_configured = main.revio_configured
        main.revio_psa_api_request = fake_request
        main.revio_configured = lambda: True
        try:
            result = await main.sync_revio_quote_approvals()
            self.assertEqual(result["approved"], 1)
            self.assertEqual(result["imported"], 0)
        finally:
            main.revio_psa_api_request = original_request
            main.revio_configured = original_configured

    async def test_exact_quote_check_can_import_an_old_approval(self):
        async def fake_request(method, path, **kwargs):
            return {"data": {
                "quoteId": 43,
                "status": "Approved",
                "createdDate": "2020-01-01T12:00:00Z",
                "customerId": 1996,
                "customerName": "Test Customer",
            }}

        db = main.SessionLocal()
        try:
            db.add(main.IntegrationSyncState(
                key=main.REVIO_QUOTE_BASELINE_KEY,
                value='{"created_at":"2026-10-30T12:00:00"}',
            ))
            db.commit()
        finally:
            db.close()

        original_request = main.revio_psa_api_request
        original_configured = main.revio_configured
        main.revio_psa_api_request = fake_request
        main.revio_configured = lambda: True
        try:
            result = await main.sync_revio_quote_approvals("43")
            self.assertEqual(result["imported"], 1)
        finally:
            main.revio_psa_api_request = original_request
            main.revio_configured = original_configured


if __name__ == "__main__":
    unittest.main()
