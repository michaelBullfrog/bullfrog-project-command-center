import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import main


class HardwareReconciliationScheduleTests(unittest.TestCase):
    def test_next_run_is_seven_am_eastern_before_schedule(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HARDWARE_ORDER_RECONCILIATION_HOUR", None)
            os.environ.pop("HARDWARE_ORDER_RECONCILIATION_TIMEZONE", None)
            result = main.next_hardware_reconciliation_at(
                datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
            )

        self.assertEqual(result, datetime(2026, 10, 16, 11, 0))

    def test_next_run_rolls_to_tomorrow_after_schedule(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HARDWARE_ORDER_RECONCILIATION_HOUR", None)
            os.environ.pop("HARDWARE_ORDER_RECONCILIATION_TIMEZONE", None)
            result = main.next_hardware_reconciliation_at(
                datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
            )

        self.assertEqual(result, datetime(2026, 10, 17, 11, 0))


if __name__ == "__main__":
    unittest.main()
