"""Independent small-board oracles and regression tests for exact search."""

import contextlib
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from sudoku_island import (
    _advance, check_uniqueness, format_pattern, main, solve,
    symmetry_orbit, validate_pattern,
)


def components(rows, width):
    """Direct graph traversal, independent of the frontier implementation."""
    remaining = {(r, c) for r, row in enumerate(rows) for c in range(width) if row & (1 << c)}
    result = []
    while remaining:
        group = {remaining.pop()}
        pending = list(group)
        while pending:
            r, c = pending.pop()
            for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    group.add(neighbor)
                    pending.append(neighbor)
        result.append(group)
    return result


def oracle_valid(rows, k, box_side):
    width = box_side**2
    grid = [[int(bool(row & (1 << c))) for c in range(width)] for row in rows]
    if any(sum(row) != k for row in grid):
        return False
    if any(sum(row[c] for row in grid) != k for c in range(width)):
        return False
    for br in range(0, width, box_side):
        for bc in range(0, width, box_side):
            if sum(grid[r][c] for r in range(br, br + box_side) for c in range(bc, bc + box_side)) != k:
                return False
    return len(components(rows, width)) == 1


def oracle_frontier(rows, width):
    groups = components(rows, width)
    bottom = len(rows) - 1
    if any(not any(r == bottom for r, _ in group) for group in groups):
        return None
    labels = {}
    frontier = []
    for c in range(width):
        group = next((i for i, cells in enumerate(groups) if (bottom, c) in cells), None)
        frontier.append(0 if group is None else labels.setdefault(group, len(labels) + 1))
    return tuple(frontier)


class ExhaustiveOracleTests(unittest.TestCase):
    def test_all_65536_binary_four_by_four_boards(self):
        possible = set()
        for rows in itertools.product(range(16), repeat=4):
            k = rows[0].bit_count()
            expected = oracle_valid(rows, k, 2)
            self.assertEqual(validate_pattern(rows, k, 2), expected, rows)
            if expected:
                possible.add(k)
        for k in range(5):
            result = solve(k, 2)
            self.assertEqual(result.status, "SAT" if k in possible else "UNSAT", k)
            if result.rows is not None:
                self.assertTrue(oracle_valid(result.rows, k, 2))

    def test_frontier_against_full_graph_for_all_prefixes_up_to_three_rows(self):
        for depth in range(1, 4):
            for rows in itertools.product(range(16), repeat=depth):
                previous = oracle_frontier(rows[:-1], 4) if depth > 1 else (0,) * 4
                if previous is not None:
                    self.assertEqual(_advance(previous, rows[-1]), oracle_frontier(rows, 4), rows)

    def test_excluding_solutions_reconstructs_the_entire_small_solution_set(self):
        expected = {
            rows for rows in itertools.product(range(16), repeat=4)
            if oracle_valid(rows, 3, 2)
        }
        found = set()
        while True:
            result = solve(3, 2, exclude=sorted(found))
            if result.status == "UNSAT":
                break
            self.assertEqual(result.status, "SAT")
            self.assertIn(result.rows, expected - found)
            found.add(result.rows)
        self.assertEqual(found, expected)
        self.assertEqual(len(found), 12)


class SolverTests(unittest.TestCase):
    def test_standard_board_minimum_and_high_quotas(self):
        for k in (0, 1, 2, 3, 4, 8, 9):
            with self.subTest(k=k):
                result = solve(k)
                self.assertEqual(result.status, "SAT" if k >= 4 else "UNSAT")
                if result.rows is not None:
                    self.assertTrue(oracle_valid(result.rows, k, 3))
        self.assertGreater(solve(3).cache_hits, 0)

    def test_one_cell_board(self):
        self.assertEqual(solve(0, 1).status, "UNSAT")
        self.assertEqual(solve(1, 1).rows, (1,))

    def test_limits_are_unknown_and_do_not_contaminate_later_searches(self):
        self.assertEqual(solve(4, max_states=1).status, "UNKNOWN")
        self.assertEqual(solve(4, timeout=1e-12).status, "UNKNOWN")
        self.assertEqual(solve(3).status, "UNSAT")

    def test_parameter_validation(self):
        for k, side in ((-1, 3), (10, 3), (1, 0), (1, -1), (True, 3), (1, 1.5)):
            with self.subTest(k=k, side=side), self.assertRaises(ValueError):
                solve(k, side)
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                solve(1, max_states=limit)
        for limit in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                solve(1, timeout=limit)

    def test_invalid_witnesses(self):
        for rows in ((), (0,) * 9, (-1,) * 9, (512,) * 9, (True,) * 9):
            self.assertFalse(validate_pattern(rows, 0))
        # Exactly one cell per row, column and box, but nine separate islands.
        rows = tuple(1 << c for c in (0, 3, 6, 1, 4, 7, 2, 5, 8))
        self.assertFalse(validate_pattern(rows, 1))

    def test_symmetries_and_uniqueness_decisions(self):
        reference = (15, 393, 408, 464, 113, 39, 60, 102, 450)
        orbit = symmetry_orbit(reference)
        self.assertEqual(len(orbit), 8)
        for image in orbit:
            self.assertTrue(validate_pattern(image, 4))
            self.assertEqual(symmetry_orbit(image), orbit)
        # Both UNIQUE and NON_UNIQUE branches are exercised on small boards.
        self.assertEqual(check_uniqueness((15,) * 4, 4, 2)["status"], "UNIQUE")
        first = solve(3, 2).rows
        result = check_uniqueness(first, 3, 2)
        self.assertEqual(result["status"], "NON_UNIQUE")
        self.assertNotIn(result["search"]["rows"], symmetry_orbit(first))
        self.assertEqual(check_uniqueness(reference, 4, max_states=1)["status"], "UNKNOWN")
        with self.assertRaises(ValueError):
            solve(4, exclude=[(0,) * 9])

    def test_orbit_against_matrix_operations(self):
        rows = (15, 393, 408, 464, 113, 39, 60, 102, 450)
        matrix = tuple(tuple(int(mask >> c & 1) for c in range(9)) for mask in rows)
        expected = set()
        for current in (matrix, tuple(tuple(reversed(row)) for row in matrix)):
            for _ in range(4):
                expected.add(tuple(sum(value << c for c, value in enumerate(row)) for row in current))
                current = tuple(zip(*current[::-1]))
        self.assertEqual(set(symmetry_orbit(rows)), expected)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(arguments)
        return code, output.getvalue()

    def test_minimum_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            code, output = self.run_cli(["--box-side", "2", "--json", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["minimum"], 3)
        self.assertEqual([r["status"] for r in report["results"]], ["UNSAT", "UNSAT", "SAT"])
        self.assertIn("Proven minimum: 3", output)

    def test_interrupted_minimum_does_not_skip_a_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            code, output = self.run_cli(["--minimum", "--max-states", "1", "--json", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 2)
        self.assertIsNone(report["minimum"])
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["status"], "UNKNOWN")
        self.assertNotIn("Proven minimum", output)

    def test_fixed_quota_and_rendering(self):
        code, output = self.run_cli(["--k", "1", "--box-side", "1"])
        self.assertEqual(code, 0)
        self.assertIn("|O|", output)
        self.assertNotIn("Proven minimum", output)
        self.assertEqual(format_pattern((1,), 1), "+-+\n|O|\n+-+")

    def test_uniqueness_cli_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            code, output = self.run_cli(["--box-side", "1", "--check-uniqueness", "--json", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["uniqueness"]["status"], "UNIQUE")
        self.assertIn("Uniqueness: UNIQUE", output)

    def test_invalid_cli_input(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--k", "10"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
