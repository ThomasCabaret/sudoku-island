"""Exhaustively characterize the minimum parity marks that orient an even island."""

from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path

from island_puzzles import ParityMark, REFERENCE_PATTERN
from sudoku_island import symmetry_orbit


def survivors(marks: tuple[ParityMark, ...]) -> tuple[tuple[int, ...], ...]:
    return tuple(pattern for pattern in symmetry_orbit(REFERENCE_PATTERN) if all(
        bool(pattern[mark.cell // 9] >> (mark.cell % 9) & 1) == mark.even for mark in marks
    ))


def orienting_pairs() -> tuple[tuple[ParityMark, ParityMark], ...]:
    marks = tuple(ParityMark(cell, bool(REFERENCE_PATTERN[cell // 9] >> (cell % 9) & 1)) for cell in range(81))
    return tuple(pair for pair in combinations(marks, 2) if len(survivors(pair)) == 1)


def analyze() -> dict:
    singles = tuple(ParityMark(cell, bool(REFERENCE_PATTERN[cell // 9] >> (cell % 9) & 1)) for cell in range(81))
    histogram = Counter(len(survivors((mark,))) for mark in singles)
    pairs = orienting_pairs()
    example = (ParityMark(0, True), ParityMark(71, False))
    return {
        "scope": "Orienting the eight proven parity masks, before any line or digit clues.",
        "reference_pattern": REFERENCE_PATTERN,
        "minimum_marks": 1 if histogram.get(1, 0) else 2 if pairs else None,
        "single_mark_cases_checked": 81,
        "single_mark_survivor_histogram": dict(sorted(histogram.items())),
        "two_cell_subsets_checked": 3240,
        "orienting_pairs_for_reference": len(pairs),
        "example": [{"cell": [m.cell // 9 + 1, m.cell % 9 + 1], "kind": "even" if m.even else "odd"} for m in example],
        "example_survivors": len(survivors(example)),
        "example_after_removing_each_mark": [len(survivors(example[:i] + example[i + 1:])) for i in range(2)],
        "proof": "No reference-consistent singleton isolates a mask. D4 symmetry carries this check to every mask. An explicit pair isolates the reference mask. Therefore the minimum is exactly two.",
        "qualification": "Minimum for orientation alone; two parity marks do not fix any digit labels. Necessity in a complete line-clue puzzle must be checked separately.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = analyze()
    print(f"Minimum: {report['minimum_marks']} parity marks; {report['orienting_pairs_for_reference']} orienting pairs for the reference mask")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
