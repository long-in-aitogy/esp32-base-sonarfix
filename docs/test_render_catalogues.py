"""Run with: python3 -m unittest discover -s docs -p 'test_*.py'."""
import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import render_catalogues as renderer


class OutputPathTests(unittest.TestCase):
    def test_output_paths_stay_inside_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "docs"
            root.mkdir()
            outside = Path(directory) / "docs-other"
            outside.mkdir()
            (root / "escape").symlink_to(outside, target_is_directory=True)
            with patch.object(renderer, "ROOT", root):
                for value in (".", "preview", str(root / "preview")):
                    with self.subTest(allowed=value):
                        self.assertTrue(renderer._output_directory(value).is_relative_to(root))
                for value in ("..", "../docs-other", str(outside), "escape/nested"):
                    with self.subTest(rejected=value):
                        with self.assertRaises(argparse.ArgumentTypeError):
                            renderer._output_directory(value)
                self.assertFalse((outside / "nested").exists())

    def test_render_rejects_output_file_symlink_before_reading_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "docs"
            root.mkdir()
            outside = Path(directory) / "sentinel.pdf"
            outside.write_bytes(b"unchanged")
            (root / "catalogue.pdf").symlink_to(outside)
            with patch.object(renderer, "ROOT", root):
                for output in (root / "catalogue.pdf", outside):
                    with self.subTest(output=output):
                        with self.assertRaises(ValueError):
                            renderer.render(root / "missing.md", output)
            self.assertEqual(outside.read_bytes(), b"unchanged")

    def test_image_paths_reject_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "docs"
            root.mkdir()
            (root / "image.png").symlink_to(Path(directory) / "outside.png")
            for value in ("../outside.png", "image.png"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        renderer._resolve_asset(root, value)


if __name__ == "__main__":
    unittest.main()
