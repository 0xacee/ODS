#!/usr/bin/env python3
"""Contract tests for the incremental mypy regression gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
GATE = ROOT_DIR / "scripts" / "check-mypy-regressions.py"


class MypyRegressionGateTests(unittest.TestCase):
    baseline_diagnostics = (
        "pkg/a.py:error: incompatible value  [assignment]",
        "pkg/b.py:error: missing annotation  [var-annotated]",
    )
    baseline_digest = hashlib.sha256(
        "\n".join(sorted(baseline_diagnostics)).encode("utf-8")
    ).hexdigest()

    def run_gate(
        self, output: str, command_exit: int = 1
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            baseline = Path(temp_dir) / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "demo": {
                            "errors": len(self.baseline_diagnostics),
                            "digest": self.baseline_digest,
                        }
                    }
                ),
                encoding="utf-8",
            )
            command = (
                "import sys; "
                f"sys.stdout.write({output!r}); "
                f"sys.exit({command_exit})"
            )
            return subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "--baseline",
                    str(baseline),
                    "--surface",
                    "demo",
                    "--",
                    sys.executable,
                    "-c",
                    command,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_known_diagnostics_pass_after_line_moves_and_reordering(self) -> None:
        result = self.run_gate(
            "pkg/b.py:91: error: missing annotation  [var-annotated]\n"
            "pkg/a.py:4: error: incompatible value  [assignment]\n"
            "Found 2 errors in 2 files (checked 2 source files)\n"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("matches the accepted baseline", result.stdout)

    def test_same_error_count_with_a_new_diagnostic_fails(self) -> None:
        result = self.run_gate(
            "pkg/a.py:10: error: incompatible value  [assignment]\n"
            "pkg/c.py:20: error: new regression  [return-value]\n"
            "Found 2 errors in 2 files (checked 3 source files)\n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("diagnostics changed without reducing type debt", result.stderr)

    def test_lower_error_count_passes_as_an_improvement(self) -> None:
        result = self.run_gate(
            "pkg/a.py:10: error: incompatible value  [assignment]\n"
            "Found 1 error in 1 file (checked 2 source files)\n"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("improved from 2 to 1", result.stdout)

    def test_non_mypy_failure_is_not_mistaken_for_a_clean_run(self) -> None:
        result = self.run_gate("mypy: command failed before checking files\n", command_exit=2)

        self.assertEqual(result.returncode, 2)
        self.assertIn("no parseable mypy diagnostics", result.stderr)


if __name__ == "__main__":
    unittest.main()
