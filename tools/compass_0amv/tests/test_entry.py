"""Entry launcher tests: pinned artifact integrity, delegation, standalone clone use."""

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "extract_0amv.py"
ARTIFACT_ZIP = ENTRY.parent / "artifact" / "compass-0amv-parser-0.1.0.zip"
ARTIFACT_ROOT = ENTRY.parent / "artifact" / "compass-0amv-parser-0.1.0"


class ArtifactIntegrityTests(unittest.TestCase):
    def test_vendored_zip_matches_pinned_sha256(self):
        expected = "325efda12ade5cc218909d339ba3afbac8d633ffa0f3680baeeb5daaa560983f"
        digest = hashlib.sha256(ARTIFACT_ZIP.read_bytes()).hexdigest()
        self.assertEqual(digest, expected)

    def test_vendored_tree_carries_same_version(self):
        init = (ARTIFACT_ROOT / "src" / "compass_0amv" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "0.1.0"', init)

    def test_source_json_provenance_present(self):
        source = (ARTIFACT_ROOT / "SOURCE.json").read_text(encoding="utf-8")
        self.assertIn("compass-0amv-extractor", source)


class EntryDelegationTests(unittest.TestCase):
    def test_help_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(ENTRY), "--help"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--compass-root", proc.stdout + proc.stderr)

    def test_missing_target_fails_without_creating_output(self):
        proc = subprocess.run(
            [sys.executable, str(ENTRY), "--compass-root",
             str(ARTIFACT_ROOT / "nonexistent-compass")],
            capture_output=True, text=True, timeout=120,
        )
        self.assertNotEqual(proc.returncode, 0)


class ArtifactSelfTests(unittest.TestCase):
    """Run the artifact's own synthetic test-suite against the vendored package."""

    def test_artifact_synthetic_suite_passes(self):
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover",
             "-s", str(ARTIFACT_ROOT / "tests"), "-v"],
            capture_output=True, text=True, timeout=300,
            env={
                **__import__("os").environ,
                "PYTHONPATH": str(ARTIFACT_ROOT / "src"),
                "PYTHONUTF8": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class VerifiedExecutionTests(unittest.TestCase):
    def load_entry(self):
        import runpy
        return runpy.run_path(str(ENTRY))

    def test_same_version_ambient_package_is_ignored(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "compass_0amv"
            package.mkdir()
            (package / "__init__.py").write_text('__version__="0.1.0"')
            (package / "extract_0amv.py").write_text('raise RuntimeError("UNVERIFIED")')
            r = subprocess.run([sys.executable, str(ENTRY), "--help"],
                               env={**os.environ, "PYTHONPATH": tmp},
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("--day-vdat", r.stdout)

    def test_missing_and_corrupt_artifact_fail_closed(self):
        import tempfile
        entry = self.load_entry()
        load = entry["load_impl"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            load.__globals__["ARTIFACT_ZIP"] = path
            with self.assertRaisesRegex(SystemExit, "missing"):
                load()
            path.write_bytes(b"invalid")
            with self.assertRaisesRegex(SystemExit, "checksum"):
                load()

    def test_expanded_tree_cannot_change_executed_parser(self):
        entry = self.load_entry()
        entry["load_impl"].__globals__["ARTIFACT_SRC"] = Path("nonexistent-expanded-tree")
        target = entry["load_impl"]()
        row = target.DAY_RECORD.pack(0, 19930103, 3.1, 3.3, 3.1, 3.3, 10)
        frame, _ = target.parse_day_vdat(target.PAGE_HEADER + row)
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(frame.iloc[0]["close"], 3.3, places=5)


if __name__ == "__main__":
    unittest.main()
