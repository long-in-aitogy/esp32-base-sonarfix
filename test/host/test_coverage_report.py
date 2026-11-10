"""Verify coverage export cannot credit mocks or discard missed source lines."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from run_coverage import ROOT, sonar_report
from host_coverage import mapped, remap_lcov


class CoverageReportTests(unittest.TestCase):
    def test_preserve_directly_compiled_production_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.cpp"
            source.write_text("int value() { return 7; }\n")
            data = f"SF:{source}\nDA:1,3\nend_of_record"
            self.assertEqual(remap_lcov(data, [source]), data)

    def test_map_only_verified_source_fragments(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.cpp"
            source.write_text("// original\nint value() {\n    return 7;\n}\n")
            fragment = "int value() {\n    return 7;\n}"
            harness = Path(directory) / "check.cpp"
            harness.write_text("int fake = 0;\n" + mapped(source, fragment) + "int test = 1;\n")
            lines = harness.read_text().splitlines()
            physical = lines.index("    return 7;") + 1
            test = lines.index("int test = 1;") + 1
            result = remap_lcov(f"SF:{harness}\nDA:{physical},3\nDA:{test},999\nend_of_record", [harness])
            self.assertIn(f"SF:{source.resolve()}\nDA:3,3", result)
            self.assertNotIn("999", result)
            changed_fragment = fragment.replace('7', '8')
            with self.assertRaises(ValueError):
                mapped(source, changed_fragment)
            source.write_text(fragment + "\n" + fragment)
            with self.assertRaises(ValueError):
                mapped(source, fragment)

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
