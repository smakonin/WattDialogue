# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.check_repo_safety import audit, findings
from scripts.export_replay import export
from wattdialogue.demo_data import write_demo_npz


class PublicationTests(unittest.TestCase):
    def test_secret_detector_reports_categories_without_values(self):
        fake_key = ("sk-" + "X" * 48).encode()
        result = findings("example.py", b"value=" + fake_key)
        self.assertEqual(result, ["credential_pattern"])
        self.assertNotIn(fake_key.decode(), str(result))
        self.assertIn("private_or_generated_file", findings(".env.local", b""))
        self.assertIn("populated_key_template", findings(".env.example", b"OPENAI_API_KEY=placeholder\n"))
        self.assertEqual(findings(".env.example", b"OPENAI_API_KEY=\nOPENAI_API_KEY_BACKUP=\n"), [])

    def test_staged_audit_checks_git_content_and_ignored_file_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text(".env\n.env.*\n!.env.example\nruntime/\n*.npz\n")
            (root / ".env.example").write_text("OPENAI_API_KEY=\nOPENAI_API_KEY_BACKUP=\n")
            (root / ".env.local").write_text("OPENAI_API_KEY=PRIVATE_TEST_VALUE\n")
            subprocess.run(["git", "add", ".gitignore", ".env.example"], cwd=root, check=True)
            self.assertTrue(audit(root)["passed"])
            ignored = subprocess.run(["git", "check-ignore", ".env.local"], cwd=root, capture_output=True, check=True)
            self.assertEqual(ignored.stdout.strip(), b".env.local")
            subprocess.run(["git", "add", "--force", ".env.local"], cwd=root, check=True)
            self.assertFalse(audit(root)["passed"])

    def test_export_excludes_reference_channels_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            write_demo_npz(source)
            path = source / "R1Hz/verification/17422.npz"
            with np.load(path) as archive:
                arrays = {key: archive[key].copy() for key in archive.files}
            arrays["P"] = np.column_stack((arrays["P"], np.full((len(arrays["t"]), 1), 98765)))
            arrays["valid"] = np.zeros(len(arrays["t"]), dtype=bool)
            arrays["reference_labels"] = np.array(["REFERENCE_ONLY"])
            np.savez_compressed(path, **arrays)
            before = path.read_bytes()
            result = export(source, root / "output")
            self.assertEqual(result["files"], 10)
            with np.load(root / "output/runs/R1Hz/verification/17422.npz") as archive:
                self.assertEqual(set(archive.files), {"t", "P", "control_P_online", "control_P_revised"})
                self.assertEqual(archive["P"].shape[1], 1)
                np.testing.assert_array_equal(archive["P"][:, 0], arrays["P"][:, 0])
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "not be replaced"):
                export(source, root / "output")


if __name__ == "__main__":
    unittest.main()
