"""Exact search for orthogonally connected binary Sudoku patterns."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Sequence


@dataclass(frozen=True)
class SearchResult:
    """SAT has a witness; only UNSAT certifies exhaustive nonexistence."""

    status: str
    box_side: int
    k: int
    rows: tuple[int, ...] | None
    states: int
    cache_hits: int
    elapsed_seconds: float
    reason: str


def _validate_parameters(box_side: int, k: int) -> int:
    if type(box_side) is not int or box_side < 1:
        raise ValueError("box_side must be a positive integer")
    width = box_side**2
    if type(k) is not int or not 0 <= k <= width:
        raise ValueError(f"k must be an integer in 0..{width}")
    return width


def validate_pattern(rows: Sequence[int], k: int, box_side: int = 3) -> bool:
    """Check a complete witness independently, including nonempty connectivity."""
    width = _validate_parameters(box_side, k)
    if len(rows) != width or any(
        type(mask) is not int or not 0 <= mask < 1 << width for mask in rows
    ):
        return False
    selected = {
        (r, c) for r in range(width) for c in range(width) if rows[r] >> c & 1
    }
    if not selected or any(mask.bit_count() != k for mask in rows):
        return False
    if any(sum((r, c) in selected for r in range(width)) != k for c in range(width)):
        return False
    for br in range(0, width, box_side):
        for bc in range(0, width, box_side):
            if sum(
                (r, c) in selected
                for r in range(br, br + box_side)
                for c in range(bc, bc + box_side)
            ) != k:
                return False
    seen = {next(iter(selected))}
    pending = list(seen)
    while pending:
        r, c = pending.pop()
        for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if neighbor in selected and neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return seen == selected


def _advance(frontier: tuple[int, ...], mask: int) -> tuple[int, ...] | None:
    """Replace the last row of a partial grid and retain its component labels.

    A component that leaves the frontier can never connect to a later row.
    Labels are canonical: 0 is empty, positive labels follow first appearance.
    """
    width = len(frontier)
    parent = list(range(2 * width + 1))

    def find(x: int) -> int:
        while parent[x] != x:
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for c in range(width):
        if mask >> c & 1:
            new = width + c + 1
            if frontier[c]:
                union(new, frontier[c])
            if c and mask >> (c - 1) & 1:
                union(new, new - 1)
    active = {find(width + c + 1) for c in range(width) if mask >> c & 1}
    if any(find(label) not in active for label in frontier if label):
        return None
    labels: dict[int, int] = {}
    result = []
    for c in range(width):
        if mask >> c & 1:
            root = find(width + c + 1)
            result.append(labels.setdefault(root, len(labels) + 1))
        else:
            result.append(0)
    return tuple(result)


class _SearchLimit(Exception):
    pass


def solve(
    k: int,
    box_side: int = 3,
    *,
    max_states: int | None = None,
    timeout: float | None = None,
    exclude: Sequence[Sequence[int]] = (),
) -> SearchResult:
    """Find one island or exhaust the finite search space.

    Exactly k cells are selected in every row, column and box. The island must
    be nonempty. Limits return UNKNOWN, never a nonexistence certificate.
    The parameter box_side generalizes the problem to box_side**2 square grids.
    Optional exclude patterns are removed from the solution space. Their
    prefix matches are part of the state key, preserving memoization safety.
    """
    width = _validate_parameters(box_side, k)
    if max_states is not None and (type(max_states) is not int or max_states < 1):
        raise ValueError("max_states must be a positive integer")
    if timeout is not None and (not 0 < timeout < float("inf")):
        raise ValueError("timeout must be positive and finite")
    started = perf_counter()
    excluded = tuple(tuple(rows) for rows in exclude)
    if any(not validate_pattern(rows, k, box_side) for rows in excluded):
        raise ValueError("Every excluded pattern must be a valid island for this quota")
    states = cache_hits = 0
    failed: set[tuple] = set()
    witness = None

    def result(status: str, reason: str) -> SearchResult:
        return SearchResult(
            status, box_side, k, witness, states, cache_hits,
            perf_counter() - started, reason,
        )

    if k == 0:
        return result("UNSAT", "An island must be nonempty.")

    candidates = []
    for columns in combinations(range(width), k):
        mask = sum(1 << c for c in columns)
        bits = tuple(int(c in columns) for c in range(width))
        boxes = tuple(sum(bits[c:c + box_side]) for c in range(0, width, box_side))
        candidates.append((mask, bits, boxes))

    # This cache is only an optimization; eviction does not remove search paths.
    advance = lru_cache(maxsize=65536)(_advance)

    def visit(
        depth: int,
        counts: tuple[int, ...],
        band: tuple[int, ...],
        frontier: tuple[int, ...],
        path: tuple[int, ...],
        matching: tuple[int, ...],
    ) -> tuple[int, ...] | None:
        nonlocal states, cache_hits
        if timeout is not None and perf_counter() - started >= timeout:
            raise _SearchLimit("Time limit reached.")
        key = (depth, counts, band, frontier, matching)
        if key in failed:
            cache_hits += 1
            return None
        if max_states is not None and states >= max_states:
            raise _SearchLimit("State limit reached.")
        states += 1
        if depth == width:
            if len(set(frontier) - {0}) == 1 and not matching:
                return path
            failed.add(key)
            return None
        remaining = width - depth - 1
        band_remaining = box_side - depth % box_side - 1
        for mask, bits, boxes in candidates:
            new_counts = tuple(a + b for a, b in zip(counts, bits))
            if any(not total <= k <= total + remaining for total in new_counts):
                continue
            new_band = tuple(a + b for a, b in zip(band, boxes))
            if any(not total <= k <= total + band_remaining * box_side for total in new_band):
                continue
            new_frontier = advance(frontier, mask)
            if new_frontier is None:
                continue
            found = visit(
                depth + 1, new_counts,
                new_band if band_remaining else (0,) * box_side,
                new_frontier, path + (mask,),
                tuple(i for i in matching if excluded[i][depth] == mask),
            )
            if found is not None:
                return found
        # Only fully explored failures are memoized. Interruptions propagate.
        failed.add(key)
        return None

    try:
        witness = visit(0, (0,) * width, (0,) * box_side, (0,) * width, (), tuple(range(len(excluded))))
    except _SearchLimit as exc:
        return result("UNKNOWN", str(exc))
    finally:
        advance.cache_clear()
        failed.clear()
    if witness is None:
        return result("UNSAT", "All candidate continuations were exhausted or soundly pruned.")
    if not validate_pattern(witness, k, box_side) or witness in excluded:
        raise RuntimeError("Internal error: the independent witness check failed")
    return result("SAT", "A witness was independently validated.")


def symmetry_orbit(rows: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    """Distinct images under the eight geometric symmetries of a square."""
    width = len(rows)
    if not width or any(type(mask) is not int or not 0 <= mask < 1 << width for mask in rows):
        raise ValueError("Expected nonempty square-board row masks")
    cells = {(r, c) for r in range(width) for c in range(width) if rows[r] >> c & 1}
    orbit = set()
    for reflected in (False, True):
        transformed = {(r, width - 1 - c) if reflected else (r, c) for r, c in cells}
        for _ in range(4):
            orbit.add(tuple(sum(1 << c for rr, c in transformed if rr == r) for r in range(width)))
            transformed = {(c, width - 1 - r) for r, c in transformed}
    return tuple(sorted(orbit))


def check_uniqueness(
    rows: Sequence[int], k: int, box_side: int = 3, *,
    max_states: int | None = None, timeout: float | None = None,
) -> dict:
    """Exhaustively seek a solution outside one geometric symmetry orbit.

    UNSAT outside the orbit proves uniqueness. A second orbit is sufficient
    to disprove it; NON_UNIQUE does not claim to count all possible orbits.
    """
    if not validate_pattern(rows, k, box_side):
        raise ValueError("Uniqueness requires a valid reference island")
    orbit = symmetry_orbit(rows)
    search = solve(k, box_side, max_states=max_states, timeout=timeout, exclude=orbit)
    return {
        "status": {"UNSAT": "UNIQUE", "SAT": "NON_UNIQUE", "UNKNOWN": "UNKNOWN"}[search.status],
        "orbit_size": len(orbit),
        "search": asdict(search),
    }


def format_pattern(rows: Sequence[int], box_side: int = 3) -> str:
    """Render row masks; the leftmost cell is bit zero."""
    width = box_side**2
    border = "+" + "+".join(["-" * box_side] * box_side) + "+"
    lines = []
    for r, mask in enumerate(rows):
        if r % box_side == 0:
            lines.append(border)
        cells = "".join("O" if mask >> c & 1 else "." for c in range(width))
        lines.append("|" + "|".join(cells[c:c + box_side] for c in range(0, width, box_side)) + "|")
    return "\n".join(lines + [border])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--k", type=int, help="test one quota (default: find the minimum)")
    mode.add_argument("--minimum", action="store_true", help="search quotas in ascending order (default)")
    parser.add_argument("--box-side", type=int, default=3, help="box width and height (default: 3)")
    parser.add_argument("--max-states", type=int, help="maximum expanded states per quota")
    parser.add_argument("--timeout", type=float, help="time limit in seconds per quota")
    parser.add_argument("--sudoku", action="store_true", help="after abstract search, complete a k=4 island with even Sudoku digits")
    parser.add_argument("--check-uniqueness", action="store_true", help="seek an island outside the witness's rotation/reflection orbit")
    parser.add_argument("--json", type=Path, metavar="PATH", help="write a machine-readable report")
    args = parser.parse_args(argv)
    try:
        width = _validate_parameters(args.box_side, args.k if args.k is not None else 0)
        if args.sudoku and (args.box_side != 3 or args.k not in (None, 4)):
            raise ValueError("--sudoku requires --box-side 3 and either --minimum or --k 4")
        quotas = (args.k,) if args.k is not None else range(1, width + 1)
        results = []
        for k in quotas:
            outcome = solve(k, args.box_side, max_states=args.max_states, timeout=args.timeout)
            results.append(outcome)
            print(f"k={k}: {outcome.status}; {outcome.states} states; {outcome.elapsed_seconds:.3f}s", flush=True)
            if outcome.rows is not None:
                print(format_pattern(outcome.rows, args.box_side))
            if args.k is None and outcome.status != "UNSAT":
                break
        last = results[-1]
        minimum = last.k if args.k is None and last.status == "SAT" else None
        if minimum is not None:
            print(f"Proven minimum: {minimum}")
        elif last.status == "UNKNOWN":
            print(f"Search incomplete: {last.reason}")
        uniqueness = None
        if args.check_uniqueness and last.rows is not None:
            print("Checking uniqueness under rotations and reflections...", flush=True)
            uniqueness = check_uniqueness(
                last.rows, last.k, args.box_side,
                max_states=args.max_states, timeout=args.timeout,
            )
            print(f"Uniqueness: {uniqueness['status']}; reference orbit size: {uniqueness['orbit_size']}")
            if uniqueness["search"]["rows"] is not None:
                print("A second island outside the reference orbit:")
                print(format_pattern(uniqueness["search"]["rows"], args.box_side))
        completion = None
        if args.sudoku and last.rows is not None:
            if last.k != 4:
                raise ValueError("Even-digit Sudoku completion requires k=4")
            from sudoku_completion import complete_sudoku, format_sudoku

            grid = complete_sudoku(last.rows)
            completion = {"status": "SAT" if grid is not None else "UNSAT", "grid": grid}
            if grid is not None:
                print("Sudoku completion: SAT (even digits match the island)")
                print(format_sudoku(grid))
            else:
                print("This pattern has no Sudoku completion; other patterns were not tested.")
        if args.json:
            report = {
                "schema_version": 1,
                "mode": "fixed" if args.k is not None else "minimum",
                "minimum": minimum,
                "results": [asdict(item) for item in results],
            }
            if args.sudoku:
                report["sudoku_completion"] = completion
            if args.check_uniqueness:
                report["uniqueness"] = uniqueness
            args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 2 if last.status == "UNKNOWN" or (uniqueness and uniqueness["status"] == "UNKNOWN") else 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
