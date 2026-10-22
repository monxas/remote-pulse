import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audit_report import main, validate


class AuditReportTests(unittest.TestCase):
    def setUp(self):
        self.inventory = "alpha==1.0\nbeta_pkg==2.0\n"
        self.report = {"dependencies": [
            {"name": "alpha", "version": "1.0", "vulns": []},
            {"name": "beta-pkg", "version": "2.0", "vulns": []},
        ], "fixes": []}

    def test_complete_clean_scan(self):
        self.assertEqual(validate(self.inventory, self.report, 0),
                         {"packages": 2, "findings": 0, "skipped": False})

    def test_findings_are_informative_with_matching_exit(self):
        self.report["dependencies"][0]["vulns"] = [{"id": "GHSA-test", "fix_versions": ["1.1"]}]
        self.assertEqual(validate(self.inventory, self.report, 1)["findings"], 1)

    def test_empty_inventory_rejected(self):
        with self.assertRaises(ValueError):
            validate("\n", self.report, 0)

    def test_empty_report_rejected(self):
        self.report["dependencies"] = []
        with self.assertRaises(ValueError):
            validate(self.inventory, self.report, 0)

    def test_skipped_package_rejected(self):
        self.report["dependencies"][0] = {"name": "alpha", "skip_reason": "unknown"}
        with self.assertRaises(ValueError):
            validate(self.inventory, self.report, 0)

    def test_missing_duplicate_and_drifted_package_rejected(self):
        for change in [lambda r: r["dependencies"].pop(),
                       lambda r: r["dependencies"].append(copy.deepcopy(r["dependencies"][0])),
                       lambda r: r["dependencies"][0].update(version="2.0")]:
            report = copy.deepcopy(self.report)
            change(report)
            with self.assertRaises(ValueError):
                validate(self.inventory, report, 0)

    def test_scanner_error_and_inconsistent_exit_rejected(self):
        for code in [1, 2, -9, True]:
            with self.assertRaises(ValueError):
                validate(self.inventory, self.report, code)
        self.report["dependencies"][0]["vulns"] = [{"id": "test", "fix_versions": []}]
        with self.assertRaises(ValueError):
            validate(self.inventory, self.report, 0)

    def test_malformed_files_and_records_fail_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, report = Path(temp) / "inventory", Path(temp) / "report"
            inventory.write_text(self.inventory)
            for contents in ["not JSON", json.dumps({}), "null"]:
                report.write_text(contents)
                with patch("sys.argv", ["audit_report.py", str(inventory), str(report), "0"]):
                    self.assertEqual(main(), 1)
        self.report["dependencies"][0]["vulns"] = [None]
        with self.assertRaises(ValueError):
            validate(self.inventory, self.report, 1)
        with self.assertRaises(ValueError):
            validate('[{"name":"alpha","version":"1.0"}]', self.report, 1)


if __name__ == "__main__":
    unittest.main()
