"""Tests for the second, independent digit-placement stage."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from sudoku_completion import complete_sudoku, validate_sudoku
from sudoku_island import main, validate_pattern


REFERENCE = (15, 393, 408, 464, 113, 39, 60, 102, 450)


class CompletionTests(unittest.TestCase):
    def test_complete_reference_island(self):
        grid = complete_sudoku(REFERENCE)
        self.assertIsNotNone(grid)
        self.assertTrue(validate_sudoku(grid, REFERENCE))
        # Independently extract the even cells and check the abstract problem.
        even_rows = tuple(sum(1 << c for c, digit in enumerate(row) if digit % 2 == 0) for row in grid)
        self.assertEqual(even_rows, REFERENCE)
        self.assertTrue(validate_pattern(even_rows, 4))
        self.assertEqual(sum(digit % 2 == 0 for row in grid for digit in row), 36)

    def test_invalid_pattern(self):
        with self.assertRaises(ValueError):
            complete_sudoku((0,) * 9)

    def test_validator_rejects_invalid_digits_and_parity(self):
        grid = complete_sudoku(REFERENCE)
        corrupted = [list(row) for row in grid]
        corrupted[0][0] = corrupted[0][1]
        self.assertFalse(validate_sudoku(corrupted, REFERENCE))
        # Globally swapping 1 and 2 preserves Sudoku rules but changes the parity pattern.
        swapped = tuple(tuple({1: 2, 2: 1}.get(digit, digit) for digit in row) for row in grid)
        self.assertFalse(validate_sudoku(swapped, REFERENCE))
        self.assertFalse(validate_sudoku((), REFERENCE))
        self.assertFalse(validate_sudoku(grid, (0,) * 9))

    def test_cli_completes_only_after_abstract_search(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--k", "4", "--sudoku", "--json", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertIsNone(report["minimum"])
        self.assertEqual(report["sudoku_completion"]["status"], "SAT")
        self.assertTrue(validate_sudoku(report["sudoku_completion"]["grid"], report["results"][0]["rows"]))

    def test_cli_rejects_wrong_quota_or_size(self):
        for arguments in (["--k", "3", "--sudoku"], ["--box-side", "2", "--sudoku"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)

    def test_interruption_does_not_attempt_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--sudoku", "--max-states", "1", "--json", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 2)
        self.assertIsNone(report["sudoku_completion"])


if __name__ == "__main__":
    unittest.main()
