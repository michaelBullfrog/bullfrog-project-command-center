import unittest

from main import (
    automation_event_reference_details,
    normalize_revio_webhook_event_type,
    revio_billing_application_rows,
    revio_webhook_value,
)


class RevioWebhookParsingTests(unittest.TestCase):
    def test_normalizes_revio_event_names(self):
        self.assertEqual(
            normalize_revio_webhook_event_type("Payment Created"),
            "PAYMENT_CREATED",
        )
        self.assertEqual(
            normalize_revio_webhook_event_type("payment-reapplied"),
            "PAYMENT_REAPPLIED",
        )

    def test_reads_case_insensitive_direct_fields(self):
        payload = {
            "EventId": "event-123",
            "EventType": "PAYMENT_CREATED",
            "ObjectId": 21165,
        }
        self.assertEqual(revio_webhook_value(payload, "event_id", "eventId"), "event-123")
        self.assertEqual(revio_webhook_value(payload, "object_id", "objectId"), 21165)

    def test_reads_nested_notification_fields(self):
        payload = {
            "notification": {
                "event_type": "PAYMENT_VOID",
                "object_id": "9988",
            }
        }
        self.assertEqual(revio_webhook_value(payload, "eventType", "event_type"), "PAYMENT_VOID")
        self.assertEqual(revio_webhook_value(payload, "objectId", "object_id"), "9988")

    def test_reads_saved_payment_reference_and_all_applied_bills(self):
        result = automation_event_reference_details(
            '{"_bullfrog":{"bill_items_loaded":true,'
            '"payment_reference":"ACH-20261019-000123456789",'
            '"customer_name":"Kettler Law Firm, PC",'
            '"bill_ids":["79311","79312"],'
            '"applications":[{"bill_id":"79311","amount":1089.50}],'
            '"bill_details":[{"bill_id":"79311","products":[]}]}}',
            None,
        )
        self.assertEqual(result["reference_number"], "ACH-20261019-000123456789")
        self.assertEqual(result["customer_name"], "Kettler Law Firm, PC")
        self.assertEqual(result["bill_ids"], ["79311", "79312"])
        self.assertTrue(result["details_loaded"])
        self.assertEqual(result["applications"][0]["amount"], 1089.50)

    def test_backfills_applied_bill_from_existing_event_detail(self):
        result = automation_event_reference_details(
            "{}",
            "Matched Payment #21165 to 1 project(s) using Bill(s) #79311, #79312.",
        )
        self.assertEqual(result["bill_ids"], ["79311", "79312"])

    def test_application_parser_accepts_nested_bill_without_amount(self):
        payload = {"records": [{"Bill": {"Id": 79311}}]}
        self.assertEqual(
            revio_billing_application_rows(payload, require_amount=False),
            [{"bill_id": "79311", "amount": None}],
        )


if __name__ == "__main__":
    unittest.main()
