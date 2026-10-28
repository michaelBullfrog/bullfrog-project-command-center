import unittest

import main


class EfaxProjectTypeTests(unittest.TestCase):
    def test_project_type_is_available(self):
        self.assertIn("Webex Calling + E-Fax", main.PROJECT_TYPES)

    def test_includes_every_webex_calling_phase_and_work_item(self):
        calling_phases = main.PHASE_TEMPLATES["Webex Calling"]
        efax_phases = {
            phase["name"]: phase
            for phase in main.PHASE_TEMPLATES["Webex Calling + E-Fax"]
        }
        for phase in calling_phases:
            self.assertEqual(efax_phases[phase["name"]], phase)

        calling_work = main.WORK_ITEM_TEMPLATES["Webex Calling"]
        efax_work = main.WORK_ITEM_TEMPLATES["Webex Calling + E-Fax"]
        self.assertTrue(all(item in efax_work for item in calling_work))

    def test_adds_efax_phase_milestones_and_engineer_work(self):
        efax_phase = next(
            phase for phase in main.PHASE_TEMPLATES["Webex Calling + E-Fax"]
            if phase["name"] == "E-Fax"
        )
        self.assertEqual(efax_phase["owner"], "engineer")
        self.assertIn("E-Fax Provisioned", efax_phase["milestones"])
        self.assertIn("E-Fax Testing Complete", efax_phase["milestones"])

        efax_work = [
            item for item in main.WORK_ITEM_TEMPLATES["Webex Calling + E-Fax"]
            if item["phase"] == "E-Fax"
        ]
        self.assertEqual(len(efax_work), 4)
        self.assertTrue(all(item["owner"] == "engineer" for item in efax_work))

    def test_keeps_webex_calling_automation_milestones(self):
        self.assertEqual(
            main.WORKFLOW_MILESTONES["Webex Calling + E-Fax"],
            main.WORKFLOW_MILESTONES["Webex Calling"],
        )


if __name__ == "__main__":
    unittest.main()
