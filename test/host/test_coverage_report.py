"""Verify coverage export cannot credit mocks or discard missed source lines."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from run_coverage import ROOT, sonar_report


class CoverageReportTests(unittest.TestCase):
    def test_merge_runs_and_keep_uncovered_production_lines(self):
        lcov = (
            f"SF:{ROOT / 'src/main.cpp'}\nDA:10,0\nDA:11,2\nend_of_record\n"
            f"SF:{ROOT / 'src/main.cpp'}\nDA:10,1\nDA:12,0\nend_of_record\n"
            f"SF:{ROOT / 'test/host/Arduino.h'}\nDA:1,999\nend_of_record\n"
            "SF:/tmp/generated-harness.cpp\nDA:1,999\nend_of_record\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "coverage.xml"
            sonar_report(lcov, output)
            files = ET.parse(output).getroot().findall("file")
            self.assertEqual([file.attrib["path"] for file in files], ["src/main.cpp"])
            self.assertEqual(
                [line.attrib for line in files[0]],
                [{"lineNumber": "10", "covered": "true"},
                 {"lineNumber": "11", "covered": "true"},
                 {"lineNumber": "12", "covered": "false"}],
            )

    def test_fail_when_only_mocks_or_no_executed_source_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "coverage.xml"
            for data in ("", f"SF:{ROOT / 'test/host/Arduino.h'}\nDA:1,3",
                         f"SF:{ROOT / 'src/main.cpp'}\nDA:10,0"):
                with self.subTest(data=data), self.assertRaises(RuntimeError):
                    sonar_report(data, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
