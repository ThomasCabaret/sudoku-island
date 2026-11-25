"""Exact freedom counts, small independent oracles and puzzle uniqueness audits."""

import contextlib
import io
import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest

from island_puzzles import (
    Line, ParityMark, REFERENCE_PATTERN, _enumerate, _renban_support, _support, analyze_freedom, audit,
    load_parity, load_puzzle, main, render_svg, validate_solution, verify,
)
from sudoku_island import symmetry_orbit
from constructions.build import build, check_png
from constructions.search import _cover, construct, reduce_lines
from constructions.parity import analyze as analyze_parity, survivors
from constructions.short_thermos import (
    check_failure_certificate, cover_without_geometry, kempe_alternatives,
    sample_grid,
)


ROOT = Path(__file__).resolve().parents[1]


class DomainSearchTests(unittest.TestCase):
    def test_renban_support_against_independent_enumeration(self):
        rng = random.Random(6)
        for _ in range(120):
            domains = tuple(sum(1 << d for d in rng.sample(range(9), rng.randrange(1, 5)))
                            for _ in range(rng.randrange(2, 5)))
            expected = [0] * len(domains)
            choices = [[d for d in range(9) if mask >> d & 1] for mask in domains]
            for assignment in itertools.product(*choices):
                if len(set(assignment)) == len(assignment) and max(assignment) - min(assignment) == len(assignment) - 1:
                    for i, value in enumerate(assignment):
                        expected[i] |= 1 << value
            self.assertEqual(_renban_support(domains), tuple(expected))

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
        cls.data, cls.lines = load_puzzle(ROOT / "constructions" / "even_island_01" / "puzzle.json")

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
        for count, expected in ((1, 8), (2, 7), (3, 1), (4, 1)):
            survivors = sum(verify(self.lines[:count], fixed_pattern=pattern).status != "UNSAT"
                            for pattern in patterns)
            self.assertEqual(survivors, expected)
        result = verify(self.lines[:3], limit=10000)
        self.assertTrue(result.exhaustive)
        self.assertEqual(len(result.solutions), 100)

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

    def test_nineteen_disjoint_cells_and_no_geometric_crossings(self):
        cells = [cell for line in self.lines for cell in line.cells]
        self.assertEqual(len(cells), 19)
        self.assertEqual(len(set(cells)), 19)
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
                code = main(["verify", str(ROOT / "constructions" / "even_island_01" / "puzzle.json"), "--json", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text())["status"], "UNIQUE")


class ConstructionTests(unittest.TestCase):
    def test_short_cover_reduction_against_brute_force(self):
        rng = random.Random(723)
        for _ in range(90):
            requirements = [rng.randrange(1, 32) for _ in range(rng.randrange(1, 7))]
            budget = rng.randrange(1, 4)
            possible = [mask for mask in range(32) if mask.bit_count() <= budget
                        and all(mask & req for req in requirements)]
            result = cover_without_geometry(requirements, [2, 3, 4, 3, 4], budget, lambda: None)
            self.assertEqual(result is not None, bool(possible))
            if result is not None:
                self.assertIn(sum(1 << i for i in result), possible)

    def test_sample_and_kempe_witnesses_are_valid_and_preserve_all_parities(self):
        grid = sample_grid(18)
        self.assertEqual(grid, sample_grid(18))
        self.assertTrue(validate_solution(grid, ()))
        digits = tuple(d for row in grid for d in row)
        for alternative in kempe_alternatives(grid):
            self.assertNotEqual(alternative, digits)
            self.assertTrue(all(a % 2 == b % 2 for a, b in zip(digits, alternative)))
            rows = tuple(tuple(alternative[r * 9:r * 9 + 9]) for r in range(9))
            self.assertTrue(validate_solution(rows, ()))

    def test_fourth_proposal_even_marks_and_short_bound(self):
        proposal = ROOT / "constructions" / "even_island_04"
        data, lines = load_puzzle(proposal / "puzzle.json")
        marks = load_parity(data)
        self.assertEqual(len(marks), 2)
        self.assertTrue(all(mark.even for mark in marks))
        self.assertEqual(len(survivors(marks)), 1)
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(len(line.cells) == 4 for line in lines))
        result = verify(lines, parity=marks)
        self.assertEqual(result.status, "UNIQUE")
        certificate = json.loads((proposal / "short-bound.json").read_text())
        self.assertEqual(certificate["target"], "".join(str(d) for row in result.solutions[0] for d in row))
        self.assertTrue(check_failure_certificate(certificate))
        self.assertEqual(certificate["max_lines"], 3)
        self.assertEqual(certificate["max_length"], 4)
        self.assertFalse(certificate["disjoint"])
        invalid = dict(certificate, witnesses=[])
        with self.assertRaises(ValueError):
            check_failure_certificate(invalid)

    def test_minimum_parity_marks_and_complete_puzzle_necessity(self):
        report = analyze_parity()
        self.assertEqual(report["minimum_marks"], 2)
        self.assertEqual(report["orienting_pairs_for_reference"], 378)
        self.assertNotIn(1, report["single_mark_survivor_histogram"])
        marks = (ParityMark(0, True), ParityMark(71, False))
        self.assertEqual(len(survivors(marks)), 1)
        self.assertEqual([len(survivors((mark,))) for mark in marks], [4, 3])
        with self.assertRaises(ValueError):
            load_parity({"parity": [{"cell": [1, 1], "kind": "even"}, {"cell": [1, 1], "kind": "odd"}]})

    def test_all_catalogue_designs_are_unique_and_irreducible(self):
        for path in sorted((ROOT / "constructions").glob("*/puzzle.json")):
            with self.subTest(proposal=path.parent.name):
                data, lines = load_puzzle(path)
                parity = load_parity(data)
                report = audit(lines, parity=parity)
                self.assertEqual(report["full"]["status"], "UNIQUE")
                self.assertTrue(report["full"]["exhaustive"])
                self.assertEqual(report["without_island_rule"]["status"], "MULTIPLE")
                for case in report["without_each_line"] + report["shortened_lines"] + report["without_each_parity_mark"]:
                    self.assertEqual(case["result"]["status"], "MULTIPLE")
                for case in report["thermometer_shortcuts"]:
                    self.assertEqual(case["result"]["status"], "MULTIPLE")
                with contextlib.redirect_stdout(io.StringIO()):
                    build(path.parent, check=True)
                svg = (path.parent / "puzzle.svg").read_text(encoding="utf-8")
                self.assertIn('width="1280" height="800"', svg)
                self.assertIn("orthogonally connected", svg)
                self.assertNotIn('class="digit"', svg)
                self.assertIn('class="digit"', (path.parent / "solution.svg").read_text(encoding="utf-8"))

    def test_mixed_reduction_keeps_whisper_semantics(self):
        data, lines = load_puzzle(ROOT / "constructions" / "even_island_03" / "puzzle.json")
        self.assertEqual([line.kind for line in lines], ["whisper", "whisper", "thermometer"])
        # A formerly redundant endpoint is put back; the reducer must remove it
        # using the whisper relation, never converting it into a thermometer.
        expanded = (Line("whisper", (8,) + lines[0].cells),) + lines[1:]
        reduced = reduce_lines(expanded)
        self.assertEqual(reduced, lines)
        self.assertEqual(verify(reduced).status, "UNIQUE")
        whispers = tuple(line for line in lines if line.kind == "whisper")
        pair = verify(whispers, limit=1000)
        self.assertTrue(pair.exhaustive)
        self.assertEqual(len(pair.solutions), 2)
        complement = tuple(tuple(10 - digit for digit in row) for row in pair.solutions[0])
        self.assertEqual(pair.solutions[1], complement)

    def test_two_anchors_exact_parity_counts(self):
        data, lines = load_puzzle(ROOT / "constructions" / "even_island_02" / "puzzle.json")
        parity = load_parity(data)
        for marks, expected in (((), 743), (parity[:1], 397), (parity[1:], 246), (parity, 1)):
            result = verify(lines, parity=marks, limit=1000)
            self.assertTrue(result.exhaustive)
            self.assertEqual(len(result.solutions), expected)

    def test_bounded_cover_against_brute_force(self):
        rng = random.Random(12)
        count = 5
        for _ in range(60):
            conflicts = [1 << i for i in range(count)]
            for i in range(count):
                for j in range(i):
                    if rng.random() < 0.2:
                        conflicts[i] |= 1 << j
                        conflicts[j] |= 1 << i
            requirements = [rng.randrange(1, 1 << count) for _ in range(rng.randrange(1, 6))]
            budget = rng.randrange(1, 4)
            feasible = []
            for mask in range(1 << count):
                chosen = [i for i in range(count) if mask >> i & 1]
                if len(chosen) <= budget and all(mask & req for req in requirements) and all(
                    not (conflicts[i] & mask & ~(1 << i)) for i in chosen
                ):
                    feasible.append(mask)
            result = _cover(requirements, conflicts, [4] * count, budget, lambda: None)
            self.assertEqual(result is not None, bool(feasible))
            if result is not None:
                self.assertIn(sum(1 << i for i in result), feasible)

    def test_search_limits_do_not_claim_impossibility(self):
        proposal = ROOT / "constructions" / "even_island_01"
        grid = json.loads((proposal / "solution.json").read_text())["grid"]
        result = construct(grid, timeout=1e-12)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.lines, ())

    def test_catalogue_sources_and_pngs_are_current(self):
        with contextlib.redirect_stdout(io.StringIO()):
            build(ROOT / "constructions" / "even_island_01", check=True)
        proposal = ROOT / "constructions" / "even_island_01"
        svg = (proposal / "puzzle.svg").read_bytes()
        with self.assertRaises(ValueError):
            check_png(proposal / "puzzle.png", svg + b"stale")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.png"
            path.write_bytes((proposal / "puzzle.png").read_bytes()[:-16])
            with self.assertRaises(ValueError):
                check_png(path, svg)


if __name__ == "__main__":
    unittest.main()
