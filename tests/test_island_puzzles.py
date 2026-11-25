"""Exact freedom counts, small independent oracles and puzzle uniqueness audits."""

import contextlib
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from island_puzzles import (
    Line, REFERENCE_PATTERN, _enumerate, _support, analyze_freedom, audit,
    load_puzzle, main, render_svg, validate_solution, verify,
)
from sudoku_island import symmetry_orbit


ROOT = Path(__file__).resolve().parents[1]


class DomainSearchTests(unittest.TestCase):
    def test_all_small_latin_squares_against_naive_enumeration(self):
        for size in (2, 3):
            units = tuple((tuple(r * size + c for c in range(size)), (1 << size) - 1)
                          for r in range(size))
            units += tuple((tuple(r * size + c for r in range(size)), (1 << size) - 1)
                           for c in range(size))
            expected = {digits for digits in itertools.product(range(1, size + 1), repeat=size**2)
                        if all(len({digits[i] for i in cells}) == size for cells, _ in units)}
            actual = set()
            _enumerate([(1 << size) - 1] * size**2, units, (), actual.add, {"states": 0}, None)
            self.assertEqual(actual, expected)

    def test_every_binary_support_table_entry(self):
        for kind, difference in (("thermometer", 5), ("whisper", 4), ("whisper", 5)):
            for reverse in (False, True):
                table = _support(kind, difference, reverse)
                for mask in range(512):
                    for a in range(1, 10):
                        expected = any(
                            ((a > b if reverse else a < b) if kind == "thermometer" else abs(a - b) >= difference)
                            for b in range(1, 10) if mask >> (b - 1) & 1
                        )
                        self.assertEqual(bool(table[mask] >> (a - 1) & 1), expected)

    def test_exact_factorization_counts(self):
        result = analyze_freedom()
        self.assertEqual(result["even_layer"]["normalized_count"], 704)
        self.assertEqual(result["odd_layer"]["normalized_count"], 19640)
        self.assertEqual(result["per_orientation"], 39820492800)
        self.assertEqual(result["total_grids"], 318563942400)
        self.assertEqual(result["even_layer"]["digit_permutations"], 24)
        self.assertEqual(result["odd_layer"]["digit_permutations"], 120)


class PuzzleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.lines = load_puzzle(ROOT / "puzzles" / "even_island.json")

    def test_unique_across_all_eight_orientations(self):
        result = verify(self.lines)
        self.assertEqual(result.status, "UNIQUE")
        self.assertTrue(result.exhaustive)
        self.assertEqual(len(result.solutions), 1)
        self.assertTrue(validate_solution(result.solutions[0], self.lines))
        grid = result.solutions[0]
        pattern = tuple(sum(1 << c for c in range(9) if grid[r][c] % 2 == 0) for r in range(9))
        self.assertEqual(pattern, REFERENCE_PATTERN)
        for image in symmetry_orbit(REFERENCE_PATTERN):
            self.assertEqual(verify(self.lines, fixed_pattern=image).status,
                             "UNIQUE" if image == pattern else "UNSAT")

    def test_each_clue_and_the_island_rule_are_essential(self):
        report = audit(self.lines)
        self.assertEqual(report["without_island_rule"]["status"], "MULTIPLE")
        for result in report["without_each_line"] + report["shortened_lines"]:
            self.assertEqual(result["result"]["status"], "MULTIPLE")
        for grid in report["without_island_rule"]["solutions"]:
            self.assertTrue(validate_solution(grid, self.lines, island=False))

    def test_orientation_then_digit_freedom(self):
        patterns = symmetry_orbit(REFERENCE_PATTERN)
        for count, expected in ((1, 8), (2, 4), (3, 1), (4, 1)):
            survivors = sum(verify(self.lines[:count], fixed_pattern=pattern).status != "UNSAT"
                            for pattern in patterns)
            self.assertEqual(survivors, expected)
        result = verify(self.lines[:3], limit=10000)
        self.assertTrue(result.exhaustive)
        self.assertEqual(len(result.solutions), 60)

    def test_unknown_never_claims_uniqueness(self):
        result = verify(self.lines, timeout=1e-12)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertFalse(result.exhaustive)
        self.assertEqual(verify(()).status, "MULTIPLE")

    def test_complement_preserves_whispers_but_breaks_thermometers(self):
        grid = verify(self.lines).solutions[0]
        complemented = tuple(tuple(10 - digit for digit in row) for row in grid)
        whisper = (Line("whisper", (23, 32, 41)),)
        self.assertTrue(validate_solution(grid, whisper))
        self.assertTrue(validate_solution(complemented, whisper))
        self.assertNotEqual(grid, complemented)
        self.assertFalse(validate_solution(complemented, self.lines))

    def test_twenty_disjoint_cells_and_no_geometric_crossings(self):
        cells = [cell for line in self.lines for cell in line.cells]
        self.assertEqual(len(cells), 20)
        self.assertEqual(len(set(cells)), 20)
        edges = [edge for line in self.lines for edge in zip(line.cells, line.cells[1:])]
        for i, (a, b) in enumerate(edges):
            for c, d in edges[i + 1:]:
                if len({a, b, c, d}) == 4:
                    self.assertNotEqual((a // 9 + b // 9, a % 9 + b % 9),
                                        (c // 9 + d // 9, c % 9 + d % 9))

    def test_invalid_line_and_search_inputs(self):
        for kind, cells in (("unknown", (0, 1)), ("whisper", (0, 0)),
                            ("thermometer", (0, 2)), ("thermometer", (0, 81))):
            with self.assertRaises(ValueError):
                Line(kind, cells)
        with self.assertRaises(ValueError):
            verify(self.lines, limit=1)
        with self.assertRaises(ValueError):
            verify(self.lines, fixed_pattern=(0,) * 9)
        self.assertFalse(validate_solution((), self.lines))

    def test_render_and_command_line(self):
        svg = render_svg(self.lines)
        self.assertEqual(svg.count("<circle"), 4)
        self.assertEqual(svg.count("<polyline"), 4)
        self.assertNotIn("<image", svg)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["verify", str(ROOT / "puzzles" / "even_island.json"), "--json", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text())["status"], "UNIQUE")


if __name__ == "__main__":
    unittest.main()
