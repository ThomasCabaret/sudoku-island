"""Search zero-given thermometer constructions by covering counterexamples.

Run from the repository root: python -m constructions.search --output output/candidate.json
Failure is relative to a finite path pool and target Sudoku, never a global
impossibility result. A candidate is accepted only by the exact Sudoku verifier.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence

from island_puzzles import Line, REFERENCE_PATTERN, line_satisfied, validate_solution, verify
from sudoku_completion import complete_sudoku


NEIGHBORS = tuple(tuple(j for j in range(81) if j != i and
                       max(abs(i // 9 - j // 9), abs(i % 9 - j % 9)) == 1) for i in range(81))


def crossing(first: tuple[int, int], second: tuple[int, int]) -> bool:
    """Unit king-grid edges cross away from endpoints only at a shared midpoint."""
    a, b = first
    c, d = second
    return len({a, b, c, d}) == 4 and (a // 9 + b // 9, a % 9 + b % 9) == (c // 9 + d // 9, c % 9 + d % 9)


def compatible(first: Line, second: Line) -> bool:
    return not set(first.cells).intersection(second.cells) and not any(
        crossing(a, b) for a in zip(first.cells, first.cells[1:])
        for b in zip(second.cells, second.cells[1:])
    )


def thermometer_pool(
    grid: Sequence[Sequence[int]], min_length: int = 4, max_length: int = 8,
    *, check_budget: Callable[[], None] = lambda: None,
) -> tuple[Line, ...]:
    """All increasing, self-avoiding, noncrossing paths within these bounds."""
    if type(min_length) is not int or type(max_length) is not int or not 2 <= min_length <= max_length <= 9:
        raise ValueError("Thermometer lengths must satisfy 2 <= min <= max <= 9")
    digits = tuple(digit for row in grid for digit in row)
    if not validate_solution(grid, ()):
        raise ValueError("The target must be a connected-even Sudoku")
    paths = []

    def extend(path: tuple[int, ...]) -> None:
        check_budget()
        if len(path) >= min_length:
            paths.append(Line("thermometer", path))
        if len(path) == max_length:
            return
        for cell in NEIGHBORS[path[-1]]:
            if digits[cell] <= digits[path[-1]]:
                continue
            edge = (path[-1], cell)
            if not any(crossing(edge, old) for old in zip(path, path[1:])):
                extend(path + (cell,))

    for cell in range(81):
        extend((cell,))
    return tuple(sorted(paths, key=lambda line: (-len(line.cells), line.cells)))


def _cover(
    requirements: Sequence[int], conflicts: Sequence[int], lengths: Sequence[int],
    max_lines: int, check_budget: Callable[[], None],
) -> tuple[int, ...] | None:
    """Exact bounded hitting set with pairwise geometry conflicts."""
    def visit(remaining: tuple[int, ...], available: int, selected: tuple[int, ...]) -> tuple[int, ...] | None:
        check_budget()
        if not remaining:
            return selected
        if len(selected) >= max_lines:
            return None
        options = min((requirement & available for requirement in remaining), key=int.bit_count)
        if not options:
            return None
        choices = []
        while options:
            bit = options & -options
            options ^= bit
            i = bit.bit_length() - 1
            choices.append((sum(bool(requirement & bit) for requirement in remaining), lengths[i], i))
        for _, _, i in sorted(choices, reverse=True):
            result = visit(tuple(req for req in remaining if not req >> i & 1),
                           available & ~conflicts[i], selected + (i,))
            if result is not None:
                return result
        return None

    return visit(tuple(requirements), (1 << len(conflicts)) - 1, ())


@dataclass(frozen=True)
class Construction:
    status: str
    lines: tuple[Line, ...]
    iterations: int
    candidate_paths: int
    elapsed_seconds: float
    reason: str


def construct(
    grid: Sequence[Sequence[int]], *, max_lines: int = 4, min_length: int = 4,
    max_length: int = 8, max_iterations: int = 200, timeout: float = 60,
    progress: Callable[[str], None] = lambda _: None,
) -> Construction:
    """Construct and trim clues; only FOUND asserts a verified unique puzzle."""
    if type(max_lines) is not int or max_lines < 1 or type(max_iterations) is not int or max_iterations < 1:
        raise ValueError("Line and iteration budgets must be positive integers")
    if not 0 < timeout < float("inf"):
        raise ValueError("Timeout must be positive and finite")
    started = perf_counter()
    deadline = started + timeout
    target = tuple(digit for row in grid for digit in row)
    pool: tuple[Line, ...] = ()
    iteration = 0

    def budget() -> None:
        if perf_counter() >= deadline:
            raise TimeoutError("Construction time budget reached")

    def outcome(status: str, reason: str, lines: Sequence[Line] = ()) -> Construction:
        return Construction(status, tuple(lines), iteration, len(pool), perf_counter() - started, reason)

    def decision(lines: Sequence[Line], limit: int = 2):
        budget()
        result = verify(lines, limit=limit, timeout=max(deadline - perf_counter(), 1e-12))
        if result.status == "UNKNOWN":
            raise TimeoutError("Sudoku verification did not finish within the construction budget")
        return result

    try:
        pool = thermometer_pool(grid, min_length, max_length, check_budget=budget)
        conflicts = []
        for i, line in enumerate(pool):
            budget()
            conflicts.append(sum(1 << j for j, other in enumerate(pool)
                                 if i == j or not compatible(line, other)))
        progress(f"Candidate paths: {len(pool)}")
        requirements: list[int] = []
        for iteration in range(1, max_iterations + 1):
            chosen = _cover(requirements, conflicts, [len(line.cells) for line in pool], max_lines, budget)
            if chosen is None:
                return outcome("NO_COVER_IN_POOL", "No compatible clue set within this path pool and line budget can isolate this target.")
            lines = [pool[i] for i in chosen]
            result = decision(lines, 20)
            if result.status == "UNSAT":
                raise RuntimeError("Construction invariant broken: the target satisfies every candidate line")
            if result.status == "UNIQUE":
                if tuple(digit for row in result.solutions[0] for digit in row) != target:
                    raise RuntimeError("Construction selected a different target")
                # Revisit all reductions until no line or endpoint can be removed.
                changed = True
                while changed:
                    changed = False
                    for i in range(len(lines)):
                        trial = lines[:i] + lines[i + 1:]
                        if decision(trial).status == "UNIQUE":
                            lines = trial
                            changed = True
                            break
                        if len(lines[i].cells) > 2:
                            for cells in (lines[i].cells[1:], lines[i].cells[:-1]):
                                trial = lines.copy()
                                trial[i] = Line("thermometer", cells)
                                if decision(trial).status == "UNIQUE":
                                    lines = trial
                                    changed = True
                                    break
                            if changed:
                                break
                # The central rule must be useful, not merely satisfied by accident.
                budget()
                without = verify(lines, island=False, timeout=max(deadline - perf_counter(), 1e-12))
                if without.status != "MULTIPLE":
                    return outcome("UNKNOWN" if without.status == "UNKNOWN" else "ISLAND_RULE_REDUNDANT",
                                   "The island rule was not proved essential; this candidate is not published.")
                return outcome("FOUND", "Exhaustively unique, with essential island rule and locally irreducible clues.", lines)
            for solution in result.solutions:
                digits = tuple(digit for row in solution for digit in row)
                if digits == target:
                    continue
                requirement = sum(1 << i for i, line in enumerate(pool) if not line_satisfied(line, digits))
                if not requirement:
                    return outcome("NO_COVER_IN_POOL", "A competing grid satisfies every candidate path in this pool.")
                if not any(old & requirement == old for old in requirements):
                    requirements = [old for old in requirements if old & requirement != requirement]
                    requirements.append(requirement)
            if iteration % 10 == 0:
                progress(f"Iteration {iteration}: {len(requirements)} counterexample constraints")
    except TimeoutError as exc:
        return outcome("UNKNOWN", str(exc))
    return outcome("UNKNOWN", "Iteration budget reached; no global impossibility claim is made.")


def puzzle_json(lines: Sequence[Line], title: str) -> dict:
    return {
        "schema_version": 1, "title": title, "givens": [],
        "rules": [
            "Place digits 1-9 once each in every row, column and 3x3 box.",
            "All cells containing an even digit form one island connected through cell sides.",
            "Digits strictly increase along each thermometer from its bulb to its tip.",
            "Lines may connect cells diagonally; diagonal contact does not connect even cells.",
        ],
        "coordinate_convention": "One-based [row, column]; the first cell is the bulb.",
        "lines": [{"kind": line.kind, "cells": [[cell // 9 + 1, cell % 9 + 1] for cell in line.cells]} for line in lines],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="candidate puzzle JSON (written only on success)")
    parser.add_argument("--target", type=Path, help="solution JSON with a grid; default: first completion of the reference island")
    parser.add_argument("--max-lines", type=int, default=4)
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=8)
    parser.add_argument("--max-iterations", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new candidate path")
        grid = json.loads(args.target.read_text(encoding="utf-8"))["grid"] if args.target else complete_sudoku(REFERENCE_PATTERN)
        result = construct(grid, max_lines=args.max_lines, min_length=args.min_length,
                           max_length=args.max_length, max_iterations=args.max_iterations,
                           timeout=args.timeout, progress=lambda text: print(text, flush=True))
        print(f"{result.status}: {result.reason} ({result.elapsed_seconds:.2f}s)")
        if result.status == "FOUND":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(puzzle_json(result.lines, "Even Island candidate"), indent=2) + "\n", encoding="utf-8")
        return 0 if result.status == "FOUND" else 2
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
