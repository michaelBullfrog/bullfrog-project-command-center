import unittest

from main import normalize_revio_webhook_event_type, revio_webhook_value


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


if __name__ == "__main__":
    unittest.main()
