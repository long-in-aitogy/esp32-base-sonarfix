"""The inventory must preserve untested code and must never create covered lines."""
from pathlib import Path
import tempfile
import unittest

from firmware_coverage_inventory import ROOT, gcov_inventory, source_fingerprint
from run_coverage import read_baseline


class FirmwareInventoryTests(unittest.TestCase):
    def test_inventory_keeps_only_project_executable_lines_as_uncovered(self):
        report = gcov_inventory(
            "version:8.4.0\nfile:src/main.cpp\nlcount:10,0,1\nlcount:11,999,0\n"
            "file:/tmp/framework.h\nlcount:1,999,0\n", ROOT)
        self.assertIn(f"SF:{ROOT / 'src/main.cpp'}", report)
        self.assertIn("DA:10,0", report)
        self.assertIn("DA:11,0", report)
        self.assertNotIn("framework", report)
        self.assertNotIn("999", report)

    def test_stale_inventory_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.lcov"
            path.write_text("TN:old-firmware\nSF:src/main.cpp\nDA:10,0\n")
            with self.assertRaises(RuntimeError):
                read_baseline(path)
            path.write_text("TN:" + source_fingerprint() + "\nSF:src/main.cpp\nDA:10,0\n")
            self.assertIn("DA:10,0", read_baseline(path))


if __name__ == "__main__":
    unittest.main()
