"""Small end-to-end campaign test; long offline searches never run in CI."""

import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchmarks.campaign import check_snapshot, pid_alive, prepare, read_json, render_status

ROOT = Path(__file__).resolve().parents[1]


class CampaignTests(unittest.TestCase):
    def test_pid_liveness_and_frozen_statement_boundary(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertFalse(pid_alive(None))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            state = prepare(output, 1800, 1800, 2, ["sat-cuts", "sat-tree"])
            self.assertEqual(len(state["jobs"]), 8)
            self.assertEqual(state["configuration"]["proof_seconds"], 1800)
            self.assertFalse(list((output / "snapshot").rglob("solution.json")))
            check_snapshot(output, state)
            source = output / "snapshot/benchmarks/solve.py"
            source.write_text("modified", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Frozen source changed"):
                check_snapshot(output, state)

    @unittest.skipUnless(importlib.util.find_spec("z3"), "Optional Z3 engine is not installed")
    def test_short_foreground_campaign_writes_terminal_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            prepare(output, 0.001, 0.001, 2, ["sat-cuts"])
            completed = subprocess.run([sys.executable, "-m", "benchmarks.campaign", "serve",
                                        "--output", str(output)], cwd=output / "snapshot",
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            state = read_json(output / "campaign.json")
            self.assertEqual(state["status"], "FINISHED")
            self.assertEqual(len(list(output.glob("*.result.json"))), 4)
            for job in state["jobs"]:
                self.assertEqual(job["state"], "FINISHED")
                result = json.loads((output / f"{job['id']}.result.json").read_text())
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIsNone(result["first_solution_seconds"])
                self.assertIsNone(result["uniqueness_search_seconds"])
            with (output / "summary.csv").open() as source:
                self.assertEqual(len(list(csv.DictReader(source))), 4)
            self.assertIn("Completed jobs: **4/4**", render_status(output, state))


if __name__ == "__main__":
    unittest.main()
