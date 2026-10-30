import unittest

import main


class HardwareWorkItemTemplateTests(unittest.TestCase):
    def test_hardware_ordering_and_tracking_are_separate_tickets(self):
        for project_type in (
            "Webex Calling",
            "Webex Calling + E-Fax",
            "Meraki",
            "Network",
        ):
            with self.subTest(project_type=project_type):
                items = main.WORK_ITEM_TEMPLATES[project_type]
                by_name = {item["name"]: item for item in items}

                self.assertNotIn("Order and Track Hardware", by_name)
                self.assertEqual(by_name["Order Hardware"]["item_type"], "Ticket")
                self.assertEqual(by_name["Order Hardware"]["owner"], "sales")
                self.assertEqual(by_name["Track Hardware Shipment"]["item_type"], "Ticket")
                self.assertEqual(by_name["Track Hardware Shipment"]["owner"], "csm")
                self.assertEqual(
                    by_name["Track Hardware Shipment"]["phase"],
                    by_name["Order Hardware"]["phase"],
                )


if __name__ == "__main__":
    unittest.main()
