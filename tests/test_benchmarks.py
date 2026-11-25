"""Independent graph oracles and rule-only solver correctness fixtures."""

import copy
import importlib.util
import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

from benchmarks.run import render_report
from benchmarks.solve import (
    METHODS, NEIGHBORS, add_tree_connectivity, components, connectivity_filter, required_bridges, solve,
)
from island_puzzles import ALL_DIGITS, EVEN, ODD

ROOT = Path(__file__).resolve().parents[1]


def connected(cells, neighbors):
    """Independent reachability oracle (no call to the implementation)."""
    if not cells:
        return False
    seen = {min(cells)}
    while True:
        enlarged = seen | {j for i in seen for j in neighbors[i] if j in cells}
        if enlarged == seen:
            return seen == cells
        seen = enlarged


class ConnectivityTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("z3"), "Optional Z3 engine is not installed")
    def test_spanning_tree_encoding_against_every_three_by_three_set(self):
        import z3
        neighbors = tuple(tuple(j for j in range(9)
                                if abs(i//3-j//3)+abs(i%3-j%3) == 1) for i in range(9))
        engine = z3.SolverFor("QF_FD")
        even = [z3.Bool(f"selected_{i}") for i in range(9)]
        add_tree_connectivity(engine, even, neighbors, 9, range(9))
        for bits in range(512):
            selected = {i for i in range(9) if bits >> i & 1}
            engine.push()
            engine.add([value if i in selected else z3.Not(value) for i, value in enumerate(even)])
            self.assertEqual(engine.check() == z3.sat, connected(selected, neighbors))
            engine.pop()

    def test_articulation_for_all_ternary_three_by_three_graphs(self):
        neighbors = tuple(tuple(j for j in range(9)
                                if abs(i//3-j//3)+abs(i%3-j%3) == 1) for i in range(9))
        # Every vertex is absent, optional, or required: all 3^9 cases.
        for state in itertools.product(range(3), repeat=9):
            possible = {i for i, value in enumerate(state) if value}
            required = {i for i, value in enumerate(state) if value == 2}
            if not required:
                continue
            reachable = next(part for part in components(possible, neighbors) if min(required) in part)
            if not required <= reachable:
                continue  # The caller rejects this contradiction before Tarjan.
            expected = {i for i in possible-required
                        if not any(required <= part for part in components(possible-{i}, neighbors))}
            self.assertEqual(required_bridges(possible, required, neighbors), expected)

    def test_filter_never_removes_known_valid_completion(self):
        grid = json.loads((ROOT / "constructions/even_island_04/solution.json").read_text())["grid"]
        bits = [1 << (digit-1) for row in grid for digit in row]
        rng = random.Random(16)
        for _ in range(300):
            domains = [bit | rng.randrange(512) for bit in bits]
            stats = {"connectivity_checks": 0}
            for _ in range(20):
                before = domains.copy()
                self.assertTrue(connectivity_filter(domains, stats))
                self.assertTrue(all(domain & bit for domain, bit in zip(domains, bits)))
                if domains == before:
                    break

    def test_wrong_parity_quotas_and_disconnected_forced_cells_fail(self):
        domains = [ALL_DIGITS]*81
        domains[:5] = [EVEN]*5
        self.assertFalse(connectivity_filter(domains, {"connectivity_checks": 0}))
        domains = [ALL_DIGITS]*81
        domains[0] = domains[80] = EVEN
        domains[1] = domains[9] = ODD
        self.assertFalse(connectivity_filter(domains, {"connectivity_checks": 0}))

    def test_lazy_component_cuts_accept_every_small_connected_set(self):
        neighbors = tuple(tuple(j for j in range(9)
                                if abs(i//3-j//3)+abs(i%3-j%3) == 1) for i in range(9))
        sets = [set(s) for s in itertools.combinations(range(9), 4)]
        valid = [s for s in sets if connected(s, neighbors)]
        for selected in sets:
            parts = components(selected, neighbors)
            if len(parts) == 1:
                continue
            for part in parts:
                boundary = set().union(*(set(neighbors[i]) for i in part))-part
                self.assertFalse(bool(part-selected or boundary.intersection(selected)))
                for other in valid:
                    self.assertTrue(bool(part-other or boundary.intersection(other)))


class RuleOnlySolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal = ROOT / "constructions/even_island_04"
        cls.data = json.loads((cls.proposal / "puzzle.json").read_text())
        cls.grid = json.loads((cls.proposal / "solution.json").read_text())["grid"]
        # Small, tractable correctness fixture with all parities PRINTED.
        # These extra marks are never used for the actual published benchmark.
        cls.data["parity"] = [{"cell": [r+1, c+1], "kind": "even" if digit % 2 == 0 else "odd"}
                              for r, row in enumerate(cls.grid) for c, digit in enumerate(row)]

    def available_methods(self):
        return [m for m in (*METHODS, "sat-tree")
                if not m.startswith("sat-") or importlib.util.find_spec("z3")]

    def test_progress_and_separate_uniqueness_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "puzzle.json"
            path.write_text(json.dumps(self.data), encoding="utf-8")
            for method in self.available_methods():
                clock = [0.0]
                events = []

                def progress(event):
                    events.append(event)
                    if event["first_solution_seconds"] is not None:
                        clock[0] = 2.0  # Past the original 1 s budget, within the new 10 s budget.

                with mock.patch("benchmarks.solve.perf_counter", side_effect=lambda: clock[0]), \
                     mock.patch("island_puzzles.perf_counter", side_effect=lambda: clock[0]):
                    result = solve(path, method, 1, proof_seconds=10, progress=progress)
                self.assertEqual(result["status"], "UNIQUE")
                self.assertEqual(result["uniqueness_search_seconds"], 2)
                self.assertEqual(events[0]["phase"], "find_solution")
                self.assertEqual(events[-1]["status"], "UNIQUE")
                self.assertTrue(any(e["status"] == "RUNNING" and e["phase"] == "prove_uniqueness" for e in events))

    def test_unique_multiple_and_unsat_without_theorem_entry_points(self):
        expected = "".join(str(d) for row in self.grid for d in row)
        import island_puzzles
        import sudoku_island
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "puzzle.json"
            with mock.patch.object(island_puzzles, "REFERENCE_PATTERN", None), \
                 mock.patch.object(island_puzzles, "symmetry_orbit", side_effect=AssertionError("Oracle used")), \
                 mock.patch.object(island_puzzles, "verify", side_effect=AssertionError("Oracle used")), \
                 mock.patch.object(sudoku_island, "solve", side_effect=AssertionError("Oracle used")):
                for method in self.available_methods():
                    for status in ("UNIQUE", "MULTIPLE", "UNSAT"):
                        with self.subTest(method=method, status=status):
                            data = copy.deepcopy(self.data)
                            if status == "MULTIPLE":
                                data["lines"] = []
                            elif status == "UNSAT":
                                data["parity"][0]["kind"] = "odd"
                            path.write_text(json.dumps(data), encoding="utf-8")
                            result = solve(path, method, 10)
                            self.assertEqual(result["status"], status)
                            if status == "UNIQUE":
                                self.assertTrue(result["exhaustive"])
                                self.assertEqual(result["solutions"], [expected])
                                self.assertIsNotNone(result["first_solution_seconds"])
                            if status == "MULTIPLE":
                                self.assertEqual(len(set(result["solutions"])), 2)

    def test_timeout_is_unknown_and_no_witness_is_invented(self):
        for method in self.available_methods():
            result = solve(self.proposal / "puzzle.json", method, 0.000001)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertFalse(result["exhaustive"])
            self.assertEqual(result["solutions"], [])
            self.assertIsNone(result["first_solution_seconds"])

    def test_report_keeps_censored_timings_and_different_work_units(self):
        rows = [{"puzzle": "a", "method": method, "status": "UNKNOWN", "solutions": [],
                 "first_solution_seconds": None, "elapsed_seconds": 1.001, "cpu_seconds": 0.9,
                 "peak_process_mib": 20, "metrics": {"states": 55,
                 "engine_statistics": {"sat decisions": 88}}} for method in METHODS]
        report = {"trials": rows, "configuration": {"seconds": 1, "repeats": 1, "methods": METHODS},
                  "environment": {"platform": "test", "python": "test", "processor": "test", "logical_cpus": 1},
                  "recorded_at_utc": "test", "puzzles": [{"path": "a", "title": "Test"}]}
        text = render_report(report)
        self.assertIn(">1 (0/1)", text)
        self.assertIn("UNKNOWN at 1 s", text)
        self.assertIn("55 nodes", text)
        self.assertIn("88 decisions", text)
        self.assertIn("no completed solve times or ranking", text)


if __name__ == "__main__":
    unittest.main()
