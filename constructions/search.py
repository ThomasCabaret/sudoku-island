"""Search zero-given thermometer constructions by covering counterexamples.

Run from the repository root: python -m constructions.search --output output/candidate.json
Failure is relative to a finite path pool and target Sudoku, never a global
impossibility result. A candidate is accepted only by the exact Sudoku verifier.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import random
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence

from island_puzzles import Line, ParityMark, REFERENCE_PATTERN, line_satisfied, load_parity, validate_solution, verify
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


def whisper_pool(
    grid: Sequence[Sequence[int]], *, seed: int = 0, samples: int = 12000,
    max_length: int = 13, limit: int = 600,
) -> tuple[Line, ...]:
    """A reproducible sampled pool of long noncrossing German whisper paths.

    This pool is deliberately bounded; it is not an enumeration of all paths.
    Every retained candidate is checked against the target before use.
    """
    if not validate_solution(grid, ()) or not 6 <= max_length <= 81 or samples < 1 or limit < 1:
        raise ValueError("Expected a valid target and positive whisper sampling bounds")
    rng = random.Random(seed)
    digits = tuple(digit for row in grid for digit in row)
    paths = set()
    for _ in range(samples):
        path = [rng.randrange(81)]
        for _ in range(max_length - 1):
            options = [cell for cell in NEIGHBORS[path[-1]] if cell not in path
                       and abs(digits[cell] - digits[path[-1]]) >= 5
                       and not any(crossing((path[-1], cell), edge) for edge in zip(path, path[1:]))]
            if not options:
                break
            path.append(rng.choice(options))
        if len(path) >= 6:
            paths.add(min(tuple(path), tuple(reversed(path))))
    return tuple(Line("whisper", path) for path in sorted(paths, key=lambda p: (-len(p), p))[:limit])


def renban_pool(
    grid: Sequence[Sequence[int]], *, seed: int = 0, samples: int = 12000,
    max_length: int = 8, limit: int = 600,
) -> tuple[Line, ...]:
    """A bounded sample of noncrossing paths whose target digits are consecutive."""
    if not validate_solution(grid, ()) or not 4 <= max_length <= 9 or samples < 1 or limit < 1:
        raise ValueError("Expected a valid target and positive renban sampling bounds")
    rng = random.Random(seed)
    digits = tuple(digit for row in grid for digit in row)
    paths = set()
    for _ in range(samples):
        path = [rng.randrange(81)]
        for _ in range(max_length - 1):
            values = {digits[cell] for cell in path}
            options = [cell for cell in NEIGHBORS[path[-1]] if digits[cell] not in values
                       and max(values | {digits[cell]}) - min(values | {digits[cell]}) < max_length
                       and not any(crossing((path[-1], cell), edge) for edge in zip(path, path[1:]))]
            if not options:
                break
            path.append(rng.choice(options))
            values.add(digits[path[-1]])
            if len(path) >= 4 and max(values) - min(values) == len(path) - 1:
                paths.add(min(tuple(path), tuple(reversed(path))))
    return tuple(Line("renban", path) for path in sorted(paths, key=lambda p: (-len(p), p))[:limit])


def _cover(
    requirements: Sequence[int], conflicts: Sequence[int], lengths: Sequence[int],
    max_lines: int, check_budget: Callable[[], None],
    blocked: Sequence[int] = (),
) -> tuple[int, ...] | None:
    """Exact bounded hitting set with pairwise geometry conflicts."""
    def visit(remaining: tuple[int, ...], available: int, selected: tuple[int, ...]) -> tuple[int, ...] | None:
        check_budget()
        mask = sum(1 << i for i in selected)
        if any(mask & rejected == rejected for rejected in blocked):
            return None
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


def reduce_lines(
    lines: Sequence[Line], *, parity: Sequence[ParityMark] = (), timeout: float = 30,
) -> tuple[Line, ...]:
    """Remove redundant lines/endpoints and legal thermometer shortcuts."""
    deadline = perf_counter() + timeout

    def decision(trial):
        remaining = deadline - perf_counter()
        if remaining <= 0:
            raise TimeoutError("Clue reduction time budget reached")
        result = verify(trial, parity=parity, timeout=remaining)
        if result.status == "UNKNOWN":
            raise TimeoutError("Clue reduction did not finish")
        return result

    initial = decision(lines)
    if initial.status != "UNIQUE":
        raise ValueError("Reduction requires a unique starting puzzle")
    target = initial.solutions[0]
    digits = tuple(digit for row in target for digit in row)
    lines = list(lines)
    changed = True
    while changed:
        changed = False
        for i in range(len(lines)):
            trial = lines[:i] + lines[i + 1:]
            if decision(trial).status == "UNIQUE":
                lines = trial
                changed = True
                break
            line = lines[i]
            if len(line.cells) > 2:
                positions = range(len(line.cells)) if line.kind == "thermometer" else (0, len(line.cells) - 1)
                for j in positions:
                    cells = line.cells[:j] + line.cells[j + 1:]
                    try:
                        replacement = Line(line.kind, cells, line.difference)
                    except ValueError:
                        continue
                    if not line_satisfied(replacement, digits):
                        continue
                    trial = lines.copy()
                    trial[i] = replacement
                    reduced = decision(trial)
                    if reduced.status == "UNIQUE" and reduced.solutions[0] == target:
                        lines = trial
                        changed = True
                        break
                if changed:
                    break
    return tuple(lines)


def construct(
    grid: Sequence[Sequence[int]], *, max_lines: int = 4, min_length: int = 4,
    max_length: int = 8, max_iterations: int = 200, timeout: float = 60,
    progress: Callable[[str], None] = lambda _: None,
    parity: Sequence[ParityMark] = (),
    candidate_lines: Sequence[Line] | None = None,
    essential_parity: bool = True,
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
        result = verify(lines, limit=limit, timeout=max(deadline - perf_counter(), 1e-12), parity=parity)
        if result.status == "UNKNOWN":
            raise TimeoutError("Sudoku verification did not finish within the construction budget")
        return result

    try:
        pool = thermometer_pool(grid, min_length, max_length, check_budget=budget) if candidate_lines is None else tuple(candidate_lines)
        if any(not line_satisfied(line, target) for line in pool):
            raise ValueError("Every candidate line must hold in the target grid")
        if not validate_solution(grid, (), parity=parity):
            raise ValueError("The target does not satisfy the parity marks")
        marked_cells = {mark.cell for mark in parity}
        pool = tuple(line for line in pool if not marked_cells.intersection(line.cells))
        conflicts = []
        for i, line in enumerate(pool):
            budget()
            conflicts.append(sum(1 << j for j, other in enumerate(pool)
                                 if i == j or not compatible(line, other)))
        progress(f"Candidate paths: {len(pool)}")
        requirements: list[int] = []
        blocked: list[int] = []
        for iteration in range(1, max_iterations + 1):
            chosen = _cover(requirements, conflicts, [len(line.cells) for line in pool], max_lines, budget, blocked)
            if chosen is None:
                if blocked:
                    return outcome("UNKNOWN", "No cover remains after heuristic rejection of redundant parity designs; other reductions may still work.")
                return outcome("NO_COVER_IN_POOL", "No compatible clue set within this path pool and line budget can isolate this target.")
            lines = [pool[i] for i in chosen]
            result = decision(lines, 20)
            if result.status == "UNSAT":
                raise RuntimeError("Construction invariant broken: the target satisfies every candidate line")
            if result.status == "UNIQUE":
                if tuple(digit for row in result.solutions[0] for digit in row) != target:
                    raise RuntimeError("Construction selected a different target")
                lines = reduce_lines(lines, parity=parity, timeout=max(deadline - perf_counter(), 1e-12))
                # The central rule must be useful, not merely satisfied by accident.
                if essential_parity and parity:
                    needed = True
                    for i in range(len(parity)):
                        budget()
                        reduced = verify(lines, parity=parity[:i] + parity[i + 1:], timeout=max(deadline - perf_counter(), 1e-12))
                        if reduced.status == "UNKNOWN":
                            raise TimeoutError("Parity necessity check did not finish")
                        if reduced.status != "MULTIPLE":
                            needed = False
                            break
                    if not needed:
                        blocked.append(sum(1 << i for i in chosen))
                        if len(blocked) % 10 == 0:
                            progress(f"Rejected {len(blocked)} redundant parity designs")
                        continue
                budget()
                without = verify(lines, island=False, timeout=max(deadline - perf_counter(), 1e-12), parity=parity)
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


def puzzle_json(lines: Sequence[Line], title: str, *, parity: Sequence[ParityMark] = ()) -> dict:
    result = {
        "schema_version": 1, "title": title, "givens": [],
        "rules": [
            "Place digits 1-9 once each in every row, column and 3x3 box.",
            "All cells containing even digits are orthogonally connected.",
            "Lines may connect cells diagonally; diagonal contact does not connect even cells.",
        ],
        "coordinate_convention": "One-based [row, column]; the first cell is the bulb.",
        "lines": [{"kind": line.kind, "cells": [[cell // 9 + 1, cell % 9 + 1] for cell in line.cells]} for line in lines],
    }
    if any(line.kind == "thermometer" for line in lines):
        result["rules"].append("Digits strictly increase along each thermometer from its bulb to its tip.")
    differences = {line.difference for line in lines if line.kind == "whisper"}
    if len(differences) > 1:
        raise ValueError("Puzzle cards use a single common whisper difference")
    if differences:
        result["rules"].append(f"Adjacent digits on green German whisper lines differ by at least {differences.pop()}.")
    if any(line.kind == "renban" for line in lines):
        result["rules"].append("Each purple renban line contains consecutive, nonrepeating digits in any order.")
    for line, item in zip(lines, result["lines"]):
        if line.kind == "whisper":
            item["difference"] = line.difference
    if parity:
        result["parity"] = [{"cell": [mark.cell // 9 + 1, mark.cell % 9 + 1], "kind": "even" if mark.even else "odd"} for mark in parity]
        result["rules"].append("Blue squares contain even digits; blue circles contain odd digits.")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="candidate puzzle JSON (written only on success)")
    parser.add_argument("--target", type=Path, help="solution JSON with a grid; default: first completion of the reference island")
    parser.add_argument("--max-lines", type=int, default=4)
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=8)
    parser.add_argument("--max-iterations", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--parity-from", type=Path, help="puzzle JSON supplying parity marks")
    parser.add_argument("--profile", choices=("thermo", "mixed", "renban"), default="thermo")
    parser.add_argument("--seed", type=int, default=0, help="whisper path sampling seed")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new candidate path")
        grid = json.loads(args.target.read_text(encoding="utf-8"))["grid"] if args.target else complete_sudoku(REFERENCE_PATTERN)
        parity = load_parity(json.loads(args.parity_from.read_text(encoding="utf-8"))) if args.parity_from else ()
        candidates = None if args.profile == "thermo" else (thermometer_pool(grid, args.min_length, args.max_length)
            + (whisper_pool(grid, seed=args.seed) if args.profile == "mixed" else renban_pool(grid, seed=args.seed)))
        result = construct(grid, max_lines=args.max_lines, min_length=args.min_length,
                           max_length=args.max_length, max_iterations=args.max_iterations,
                           timeout=args.timeout, progress=lambda text: print(text, flush=True), parity=parity,
                           candidate_lines=candidates)
        print(f"{result.status}: {result.reason} ({result.elapsed_seconds:.2f}s)")
        if result.status == "FOUND":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(puzzle_json(result.lines, "Even Island candidate", parity=parity), indent=2) + "\n", encoding="utf-8")
        return 0 if result.status == "FOUND" else 2
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
