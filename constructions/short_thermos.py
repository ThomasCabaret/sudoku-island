"""Search short thermometers with the entire parity geometry fixed first.

The final puzzle uses two even marks, not 81 printed parity clues. Every
published candidate is verified again across all eight possible island masks.
"""

from __future__ import annotations

import argparse
from itertools import combinations, permutations
from functools import lru_cache
import json
from pathlib import Path
import random
from time import perf_counter

from island_puzzles import (
    EVEN, ODD, UNITS, Line, REFERENCE_PATTERN, _enumerate, line_satisfied,
    validate_solution, verify,
)
from constructions.parity import orienting_pairs
from constructions.search import _cover, compatible, puzzle_json, thermometer_pool


def sample_grid(seed: int) -> tuple[tuple[int, ...], ...]:
    """Reproducible varied completions, not a uniform sample of all Sudokus."""
    rng = random.Random(seed)
    cells = list(range(81))
    rng.shuffle(cells)
    index = {cell: i for i, cell in enumerate(cells)}
    units = tuple((tuple(index[cell] for cell in unit), 511) for unit in UNITS)
    domains = [EVEN if REFERENCE_PATTERN[cell // 9] >> (cell % 9) & 1 else ODD for cell in cells]
    solution = None

    class Found(Exception):
        pass

    def accept(values):
        nonlocal solution
        digits = [0] * 81
        mapping = {}
        for group in ((2, 4, 6, 8), (1, 3, 5, 7, 9)):
            images = list(group)
            rng.shuffle(images)
            mapping.update(zip(group, images))
        for i, value in enumerate(values):
            digits[cells[i]] = mapping[value]
        solution = tuple(tuple(digits[r * 9:r * 9 + 9]) for r in range(9))
        raise Found

    try:
        _enumerate(domains, units, (), accept, {"states": 0}, None)
    except Found:
        pass
    if solution is None or not validate_solution(solution, ()):
        raise RuntimeError("Failed to obtain a validated sample completion")
    return solution


def relabel_grid(grid, index):
    """One of all 4! * 5! global parity-preserving digit relabelings."""
    if not 0 <= index < 2880:
        raise ValueError("Relabeling index must be in 0..2879")
    evens = tuple(permutations((2, 4, 6, 8)))[index // 120]
    odds = tuple(permutations((1, 3, 5, 7, 9)))[index % 120]
    mapping = dict(zip((2, 4, 6, 8), evens))
    mapping.update(zip((1, 3, 5, 7, 9), odds))
    return tuple(tuple(mapping[d] for d in row) for row in grid)


def kempe_alternatives(grid):
    """Valid alternatives obtained by swapping a bichromatic graph component."""
    digits = tuple(value for row in grid for value in row)
    peers = [set().union(*(set(unit) for unit in UNITS if cell in unit)) - {cell} for cell in range(81)]
    for group in ((2, 4, 6, 8), (1, 3, 5, 7, 9)):
        for a, b in combinations(group, 2):
            remaining = {cell for cell, value in enumerate(digits) if value in (a, b)}
            while remaining:
                component = {min(remaining)}
                remaining -= component
                pending = list(component)
                while pending:
                    adjacent = peers[pending.pop()] & remaining
                    remaining -= adjacent
                    component |= adjacent
                    pending.extend(adjacent)
                alternative = tuple(a + b - value if cell in component else value for cell, value in enumerate(digits))
                yield alternative


def cover_without_geometry(requirements, lengths, max_lines, budget):
    """Exact small hitting set after merging dominated counterexample covers.

    This optimization applies only when shared cells/crossings are allowed.
    A dominating path can always replace a weaker cover of the current
    counterexamples. New counterexamples recompute this reduction from scratch.
    """
    if not requirements:
        return ()
    if any(mask == 0 for mask in requirements):
        return None
    coverage = {}
    for i in range(len(lengths)):
        budget()
        mask = sum(1 << j for j, req in enumerate(requirements) if req >> i & 1)
        if mask and (mask not in coverage or lengths[i] > lengths[coverage[mask]]):
            coverage[mask] = i
    maximal = []
    for mask, i in sorted(coverage.items(), key=lambda item: -item[0].bit_count()):
        if not any(mask & other == mask for other, _ in maximal):
            maximal.append((mask, i))
    by_requirement = [[(mask, i) for mask, i in maximal if mask >> j & 1] for j in range(len(requirements))]

    @lru_cache(maxsize=None)
    def visit(remaining, slots):
        budget()
        if not remaining:
            return ()
        if not slots:
            return None
        gains = [((mask & remaining).bit_count(), mask, i) for mask, i in maximal]
        if max(gain for gain, _, _ in gains) * slots < remaining.bit_count():
            return None
        if slots == 1:
            return next(((i,) for _, mask, i in gains if remaining & ~mask == 0), None)
        choice = min((j for j in range(len(requirements)) if remaining >> j & 1),
                     key=lambda j: len(by_requirement[j]))
        for mask, i in sorted(by_requirement[choice], key=lambda item: -(item[0] & remaining).bit_count()):
            result = visit(remaining & ~mask, slots - 1)
            if result is not None:
                return (i,) + result
        return None

    return visit((1 << len(requirements)) - 1, max_lines)


def search_target(grid, *, max_lines=3, max_length=4, timeout=10, disjoint=True):
    """Exact cover of sampled counterexamples, followed by exhaustive verification.

    NO_COVER_IN_POOL concerns this target and its complete bounded path pool.
    Time exhaustion is UNKNOWN. All discovered witnesses retain the target.
    """
    started = perf_counter()
    if type(max_lines) is not int or max_lines < 1 or not 0 < timeout < float("inf"):
        raise ValueError("Positive line and time budgets are required")
    pattern = tuple(sum(1 << c for c, value in enumerate(row) if value % 2 == 0) for row in grid)
    if pattern != REFERENCE_PATTERN or not validate_solution(grid, ()):
        raise ValueError("The target must be a Sudoku with the reference parity geometry")
    deadline = started + timeout
    target = tuple(value for row in grid for value in row)
    pool = thermometer_pool(grid, 2, max_length)
    requirements = []
    witnesses = {}
    iterations = 0

    def budget():
        if perf_counter() >= deadline:
            raise TimeoutError

    def add(alternative):
        mask = sum(1 << i for i, line in enumerate(pool) if not line_satisfied(line, alternative))
        if not any(old & mask == old for old in requirements):
            requirements[:] = [old for old in requirements if old & mask != mask]
            requirements.append(mask)
            witnesses[mask] = alternative

    try:
        for alternative in kempe_alternatives(grid):
            budget()
            add(alternative)
        conflicts = []
        for i, line in enumerate(pool):
            budget()
            conflicts.append((1 << i) if not disjoint else sum(
                1 << j for j, other in enumerate(pool) if i == j or not compatible(line, other)
            ))
        while True:
            budget()
            iterations += 1
            lengths = [len(line.cells) for line in pool]
            chosen = (_cover(requirements, conflicts, lengths, max_lines, budget) if disjoint
                      else cover_without_geometry(requirements, lengths, max_lines, budget))
            if chosen is None:
                certificate = {
                    "schema_version": 1,
                    "scope": "This target filling only; the entire parity geometry is fixed.",
                    "target": "".join(map(str, target)),
                    "max_lines": max_lines, "max_length": max_length,
                    "disjoint": disjoint,
                    "path_convention": "All self-avoiding, noncrossing king-adjacent increasing paths of length 2..max_length.",
                    "witnesses": ["".join(map(str, witnesses[mask])) for mask in requirements],
                }
                return {"status": "NO_COVER_IN_POOL", "paths": len(pool), "iterations": iterations,
                        "certificate": certificate}, None
            lines = tuple(pool[i] for i in chosen)
            result = verify(lines, fixed_pattern=REFERENCE_PATTERN, limit=20, timeout=max(deadline - perf_counter(), 1e-12))
            if result.status == "UNKNOWN":
                raise TimeoutError
            if result.status == "UNIQUE":
                if tuple(d for row in result.solutions[0] for d in row) != target:
                    raise RuntimeError("Target preservation failed")
                return {"status": "FOUND_FIXED_GEOMETRY", "paths": len(pool), "iterations": iterations}, lines
            for solution in result.solutions:
                alternative = tuple(digit for row in solution for digit in row)
                if alternative != target:
                    add(alternative)
    except TimeoutError:
        return {"status": "UNKNOWN", "paths": len(pool), "iterations": iterations}, None


def check_failure_certificate(certificate):
    """Check witnesses and use the separate generic cover solver for the bound."""
    def grid_from_string(text):
        if not isinstance(text, str) or len(text) != 81 or any(c not in "123456789" for c in text):
            raise ValueError("Expected an 81-digit grid")
        return tuple(tuple(map(int, text[r * 9:r * 9 + 9])) for r in range(9))

    if certificate.get("schema_version") != 1:
        raise ValueError("Unknown certificate format")
    target = grid_from_string(certificate["target"])
    if not validate_solution(target, ()):
        raise ValueError("Invalid target Sudoku")
    pattern = tuple(sum(1 << c for c, d in enumerate(row) if d % 2 == 0) for row in target)
    if pattern != REFERENCE_PATTERN:
        raise ValueError("The certificate must use the reference parity geometry")
    max_lines, max_length = certificate["max_lines"], certificate["max_length"]
    if type(max_lines) is not int or not 1 <= max_lines <= 8 or type(certificate["disjoint"]) is not bool:
        raise ValueError("Invalid cover bounds")
    pool = thermometer_pool(target, 2, max_length)
    requirements = []
    for text in certificate["witnesses"]:
        alternative = grid_from_string(text)
        mask = tuple(sum(1 << c for c, d in enumerate(row) if d % 2 == 0) for row in alternative)
        if alternative == target or mask != pattern or not validate_solution(alternative, ()):
            raise ValueError("Invalid alternative in the certificate")
        values = tuple(d for row in alternative for d in row)
        requirements.append(sum(1 << i for i, line in enumerate(pool) if not line_satisfied(line, values)))
    conflicts = [(sum(1 << j for j, other in enumerate(pool) if i == j or not compatible(line, other))
                  if certificate["disjoint"] else 1 << i) for i, line in enumerate(pool)]
    # This deliberately uses the original generic solver, not the new
    # dominance-based cover_without_geometry implementation.
    result = _cover(requirements, conflicts, [len(line.cells) for line in pool], max_lines, lambda: None)
    if result is not None:
        raise ValueError("The alternatives do not establish the claimed lower bound")
    return True


def choose_even_marks(lines, *, require_essential=True):
    cells = {cell for line in lines for cell in line.cells}
    pairs = [pair for pair in orienting_pairs() if all(mark.even and mark.cell not in cells for mark in pair)]
    pairs.sort(key=lambda pair: -sum(abs(a - b) for a, b in zip(divmod(pair[0].cell, 9), divmod(pair[1].cell, 9))))
    for pair in pairs:
        if verify(lines, parity=pair).status != "UNIQUE":
            continue
        if require_essential and any(verify(lines, parity=(mark,)).status != "MULTIPLE" for mark in pair):
            continue
        if verify(lines, island=False, parity=pair).status == "MULTIPLE":
            return pair
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--target", type=Path, help="one solution JSON; otherwise sample completions")
    source.add_argument("--relabel-from", type=Path, help="relabel this solution; use --targets 2880 to exhaust its digit permutations")
    parser.add_argument("--certificate", type=Path, help="save a fixed-target negative certificate")
    parser.add_argument("--check-certificate", type=Path)
    parser.add_argument("--targets", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-lines", type=int, default=3)
    parser.add_argument("--max-length", type=int, default=4)
    parser.add_argument("--seconds-per-target", type=float, default=5)
    parser.add_argument("--allow-overlap", action="store_true")
    args = parser.parse_args()
    if args.check_certificate:
        check_failure_certificate(json.loads(args.check_certificate.read_text(encoding="utf-8")))
        print("Verified fixed-target short-thermometer lower bound (not a global impossibility claim).")
        return 0
    if args.output is None or args.targets < 1:
        parser.error("Specify --output and a positive number of target samples")
    if args.seed < 0 or args.max_lines < 1 or not 2 <= args.max_length <= 9 or not 0 < args.seconds_per_target < float("inf"):
        parser.error("Use a nonnegative seed, positive search budgets and a maximum length in 2..9")
    if args.certificate and not args.target:
        parser.error("--certificate requires a single --target")
    if args.output.exists():
        parser.error("Output already exists")
    records = []
    base = json.loads(args.relabel_from.read_text(encoding="utf-8"))["grid"] if args.relabel_from else None
    stop = args.seed + (1 if args.target else args.targets)
    if base is not None:
        if args.seed >= 2880:
            parser.error("A relabeling seed must be in 0..2879")
        stop = min(stop, 2880)
    for seed in range(args.seed, stop):
        grid = (json.loads(args.target.read_text(encoding="utf-8"))["grid"] if args.target else
                relabel_grid(base, seed) if base is not None else sample_grid(seed))
        result, lines = search_target(grid, max_lines=args.max_lines, max_length=args.max_length,
                                      timeout=args.seconds_per_target, disjoint=not args.allow_overlap)
        result["seed"] = seed
        certificate = result.pop("certificate", None)
        if certificate is not None and args.certificate:
            args.certificate.parent.mkdir(parents=True, exist_ok=True)
            args.certificate.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
        records.append(result)
        if len(records) % 10 == 1 or lines is not None:
            print(result, flush=True)
        if lines is not None:
            marks = choose_even_marks(lines)
            if marks is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(puzzle_json(lines, "Two Even Anchors", parity=marks), indent=2) + "\n", encoding="utf-8")
                return 0
            print("No nonredundant off-line even-mark pair for this candidate", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Selected targets only, not all possible digit fillings.",
              "mode": "fixed_target" if args.target else "relabeling" if base is not None else "sampling",
              "max_lines": args.max_lines, "max_length": args.max_length,
              "disjoint": not args.allow_overlap, "records": records}
    args.output.with_suffix(".search.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
