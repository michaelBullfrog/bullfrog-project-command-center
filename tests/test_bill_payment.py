import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import main


class BillPaymentStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_amount_applied_to_selected_bill(self):
        selected_bill = {
            "source_type": "Bill",
            "source_number": "79311",
            "bill_id": "79311",
            "bill_amount_due": Decimal("1089.50"),
        }
        responses = [
            {
                "records": [{
                    "payment_id": 21165,
                    "customer_id": 1996,
                    "amount": 1122.51,
                    "refund_flag": False,
                    "bounced": False,
                }]
            },
            {
                "records": [{
                    "payment_id": 21165,
                    "bill_id": 79311,
                    "amount_applied": 1089.50,
                }]
            },
        ]
        with patch.object(main, "revio_billing_get", AsyncMock(side_effect=responses)):
            result = await main.revio_billing_bill_payment_status("1996", selected_bill)

        self.assertTrue(result["paid"])
        self.assertEqual(result["amount_applied"], Decimal("1089.50"))
        self.assertEqual(result["remaining"], Decimal("0"))
        self.assertEqual(result["payments"][0]["payment_id"], "21165")

    async def test_partial_payment_keeps_bill_waiting(self):
        selected_bill = {
            "source_type": "Bill",
            "source_number": "79311",
            "bill_id": "79311",
            "bill_amount_due": Decimal("1089.50"),
        }
        responses = [
            {"records": [{"payment_id": 21165, "refund_flag": False, "bounced": False}]},
            {"records": [{"bill_id": 79311, "amount": 500}]},
        ]
        with patch.object(main, "revio_billing_get", AsyncMock(side_effect=responses)):
            result = await main.revio_billing_bill_payment_status("1996", selected_bill)

        self.assertFalse(result["paid"])
        self.assertEqual(result["amount_applied"], Decimal("500"))
        self.assertEqual(result["remaining"], Decimal("589.50"))

    async def test_refunded_payment_is_not_counted(self):
        selected_bill = {
            "source_type": "Bill",
            "source_number": "79311",
            "bill_id": "79311",
            "bill_amount_due": Decimal("1089.50"),
        }
        with patch.object(
            main,
            "revio_billing_get",
            AsyncMock(return_value={
                "records": [{
                    "payment_id": 21165,
                    "refund_flag": True,
                    "bounced": False,
                }]
            }),
        ) as billing_get:
            result = await main.revio_billing_bill_payment_status("1996", selected_bill)

        self.assertFalse(result["paid"])
        self.assertEqual(result["amount_applied"], Decimal("0"))
        self.assertEqual(billing_get.await_count, 1)


if __name__ == "__main__":
    unittest.main()
