"""Analyze digit freedom and verify line-clue puzzles with a connected even island.

The eight parity masks come from the independently established abstract island
theorem (see docs/completeness.tex). No particular Sudoku filling is assumed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from functools import lru_cache
import json
from math import factorial, log2
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence

from sudoku_completion import validate_sudoku
from sudoku_island import symmetry_orbit, validate_pattern


REFERENCE_PATTERN = (15, 393, 408, 464, 113, 39, 60, 102, 450)
ALL_DIGITS = 511
EVEN = sum(1 << (digit - 1) for digit in (2, 4, 6, 8))
ODD = ALL_DIGITS ^ EVEN
UNITS = tuple(
    [tuple(r * 9 + c for c in range(9)) for r in range(9)]
    + [tuple(r * 9 + c for r in range(9)) for c in range(9)]
    + [tuple((br + r) * 9 + bc + c for r in range(3) for c in range(3))
       for br in range(0, 9, 3) for bc in range(0, 9, 3)]
)


@dataclass(frozen=True)
class Line:
    """A path of cell indices 0..80; a thermometer starts at its bulb."""

    kind: str
    cells: tuple[int, ...]
    difference: int = 5

    def __post_init__(self) -> None:
        if self.kind not in ("thermometer", "whisper"):
            raise ValueError("Line kind must be thermometer or whisper")
        if not 2 <= len(self.cells) <= 81 or len(set(self.cells)) != len(self.cells):
            raise ValueError("A line needs at least two distinct cells and cannot repeat a cell")
        if any(type(cell) is not int or not 0 <= cell < 81 for cell in self.cells):
            raise ValueError("Cell indices must be integers in 0..80")
        if any(max(abs(a // 9 - b // 9), abs(a % 9 - b % 9)) != 1
               for a, b in zip(self.cells, self.cells[1:])):
            raise ValueError("Consecutive line cells must touch by a side or corner")
        if type(self.difference) is not int or not 1 <= self.difference <= 8:
            raise ValueError("Whisper difference must be an integer in 1..8")


@dataclass(frozen=True)
class Verification:
    status: str
    solutions: tuple[tuple[tuple[int, ...], ...], ...]
    exhaustive: bool
    states: int
    elapsed_seconds: float
    reason: str


class _StopSearch(Exception):
    pass


@lru_cache(maxsize=16)
def _support(kind: str, difference: int, reverse: bool) -> tuple[int, ...]:
    """Allowed digits at one endpoint, given the other endpoint's domain."""
    return tuple(
        sum(1 << (a - 1) for a in range(1, 10) if any(
            ((a > b if reverse else a < b) if kind == "thermometer"
             else abs(a - b) >= difference)
            for b in range(1, 10) if mask >> (b - 1) & 1
        ))
        for mask in range(512)
    )


def _enumerate(
    initial: list[int],
    units: tuple[tuple[tuple[int, ...], int], ...],
    lines: Sequence[Line],
    accept: Callable[[tuple[int, ...]], None],
    stats: dict[str, int],
    deadline: float | None,
) -> None:
    """Exhaustive domain search; callbacks may explicitly interrupt enumeration."""
    peers = [set().union(*(set(cells) for cells, _ in units if i in cells)) - {i}
             for i in range(len(initial))]
    arcs = [(a, b, _support(line.kind, line.difference, False),
             _support(line.kind, line.difference, True))
            for line in lines for a, b in zip(line.cells, line.cells[1:])]

    def visit(domains: list[int]) -> None:
        if deadline is not None and perf_counter() >= deadline:
            raise TimeoutError("Time limit reached before enumeration finished")
        stats["states"] += 1
        while True:
            changed = False
            for i, domain in enumerate(domains):
                if not domain:
                    return
                if domain.bit_count() == 1:
                    for j in peers[i]:
                        if domains[j] & domain:
                            domains[j] ^= domain
                            if not domains[j]:
                                return
                            changed = True
            for a, b, ab, ba in arcs:
                da, db = domains[a] & ab[domains[b]], domains[b] & ba[domains[a]]
                if not da or not db:
                    return
                if da != domains[a] or db != domains[b]:
                    domains[a], domains[b] = da, db
                    changed = True
            for cells, required in units:
                bits = required
                while bits:
                    bit = bits & -bits
                    bits ^= bit
                    places = [i for i in cells if domains[i] & bit]
                    if not places:
                        return
                    if len(places) == 1 and domains[places[0]] != bit:
                        domains[places[0]] = bit
                        changed = True
            if not changed:
                break
        choices = [i for i, domain in enumerate(domains) if domain.bit_count() > 1]
        if not choices:
            accept(tuple(domain.bit_length() for domain in domains))
            return
        cell = min(choices, key=lambda i: domains[i].bit_count())
        bits = domains[cell]
        while bits:
            bit = bits & -bits
            bits ^= bit
            branch = domains.copy()
            branch[cell] = bit
            visit(branch)

    visit(initial.copy())


def line_satisfied(line: Line, digits: Sequence[int]) -> bool:
    return all(
        digits[a] < digits[b] if line.kind == "thermometer"
        else abs(digits[a] - digits[b]) >= line.difference
        for a, b in zip(line.cells, line.cells[1:])
    )


def validate_solution(grid: Sequence[Sequence[int]], lines: Sequence[Line], *, island: bool = True) -> bool:
    """Whole-grid checker using direct quotas, Sudoku sets and graph traversal."""
    if len(grid) != 9 or any(len(row) != 9 for row in grid):
        return False
    if any(type(digit) is not int or not 1 <= digit <= 9 for row in grid for digit in row):
        return False
    rows = tuple(sum(1 << c for c, digit in enumerate(row) if digit % 2 == 0) for row in grid)
    digits = tuple(digit for row in grid for digit in row)
    return (validate_sudoku(grid, rows)
            and (not island or validate_pattern(rows, 4))
            and all(line_satisfied(line, digits) for line in lines))


def verify(
    lines: Sequence[Line], *, island: bool = True, limit: int = 2,
    timeout: float | None = None, fixed_pattern: Sequence[int] | None = None,
) -> Verification:
    """Enumerate up to limit solutions across all eight island orientations.

    UNIQUE requires full exhaustion with exactly one solution. Finding two
    witnesses already proves MULTIPLE. Timeouts never prove uniqueness.
    With island=False this searches all ordinary Sudokus with the line clues.
    """
    if type(limit) is not int or limit < 2:
        raise ValueError("Solution limit must be an integer of at least two")
    if timeout is not None and not 0 < timeout < float("inf"):
        raise ValueError("Timeout must be positive and finite")
    if fixed_pattern is not None and (not island or not validate_pattern(fixed_pattern, 4)):
        raise ValueError("A fixed pattern requires island=True and a valid k=4 island")
    started = perf_counter()
    deadline = None if timeout is None else started + timeout
    solutions: list[tuple[tuple[int, ...], ...]] = []
    stats = {"states": 0}
    exhaustive = True
    reason = "The entire solution space was exhausted."

    def accept(digits: tuple[int, ...]) -> None:
        grid = tuple(tuple(digits[r * 9:r * 9 + 9]) for r in range(9))
        if not validate_solution(grid, lines, island=island):
            raise RuntimeError("The independent whole-grid validator rejected a solution")
        solutions.append(grid)
        if len(solutions) >= limit:
            raise _StopSearch

    patterns = ((tuple(fixed_pattern),) if fixed_pattern is not None
                else symmetry_orbit(REFERENCE_PATTERN)) if island else (None,)
    try:
        for pattern in patterns:
            domains = [EVEN if pattern[r] >> c & 1 else ODD
                       for r in range(9) for c in range(9)] if pattern is not None else [ALL_DIGITS] * 81
            _enumerate(domains, tuple((unit, ALL_DIGITS) for unit in UNITS), lines, accept, stats, deadline)
    except _StopSearch:
        exhaustive = False
        reason = f"At least {limit} distinct solutions were found."
    except TimeoutError as exc:
        exhaustive = False
        reason = str(exc)
    status = ("MULTIPLE" if len(solutions) >= 2 else "UNKNOWN" if not exhaustive
              else "UNIQUE" if solutions else "UNSAT")
    return Verification(status, tuple(solutions), exhaustive, stats["states"], perf_counter() - started, reason)


def count_layer(pattern: Sequence[int], even: bool) -> dict:
    """Count a parity layer modulo digit relabeling, with no sampling or limits.

    Fix its first-row cells to its digits in ascending order. Each unrestricted
    coloring has exactly one representative after a global digit permutation.
    """
    if not validate_pattern(pattern, 4):
        raise ValueError("Expected a valid standard k=4 island")
    cells = tuple(r * 9 + c for r in range(9) for c in range(9)
                  if bool(pattern[r] >> c & 1) == even)
    index = {cell: i for i, cell in enumerate(cells)}
    required = EVEN if even else ODD
    layer_units = tuple((tuple(index[cell] for cell in unit if cell in index), required) for unit in UNITS)
    domains = [required] * len(cells)
    digits = [digit for digit in range(1, 10) if required >> (digit - 1) & 1]
    for cell, digit in zip(layer_units[0][0], digits):
        domains[cell] = 1 << (digit - 1)
    count = 0

    def accept(_: tuple[int, ...]) -> None:
        nonlocal count
        count += 1

    stats = {"states": 0}
    started = perf_counter()
    _enumerate(domains, layer_units, (), accept, stats, None)
    return {"normalized_count": count, "digit_permutations": factorial(len(digits)),
            "labeled_count": count * factorial(len(digits)), "states": stats["states"],
            "elapsed_seconds": perf_counter() - started, "exhaustive": True}


def analyze_freedom() -> dict:
    even, odd = count_layer(REFERENCE_PATTERN, True), count_layer(REFERENCE_PATTERN, False)
    orientations = len(symmetry_orbit(REFERENCE_PATTERN))
    per_orientation = even["labeled_count"] * odd["labeled_count"]
    total = orientations * per_orientation
    return {"even_layer": even, "odd_layer": odd, "orientations": orientations,
            "per_orientation": per_orientation, "total_grids": total,
            "log2_total_grids": log2(total)}


def load_puzzle(path: Path) -> tuple[dict, tuple[Line, ...]]:
    """Load the documented JSON format; coordinates are one-based (row, column)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("givens") != []:
        raise ValueError("Expected schema_version 1 and an empty givens list")
    lines = []
    for item in data["lines"]:
        coords = item["cells"]
        if any(len(pair) != 2 or any(type(x) is not int or not 1 <= x <= 9 for x in pair) for pair in coords):
            raise ValueError("Coordinates must be integer row/column pairs in 1..9")
        lines.append(Line(item["kind"], tuple((r - 1) * 9 + c - 1 for r, c in coords), item.get("difference", 5)))
    return data, tuple(lines)


def audit(lines: Sequence[Line]) -> dict:
    """Verify uniqueness, orientation, necessity of each line and of the island rule."""
    full = verify(lines)
    orientations = [{"pattern": pattern, "result": asdict(verify(lines, fixed_pattern=pattern))}
                    for pattern in symmetry_orbit(REFERENCE_PATTERN)]
    removals = [{"removed_line": i + 1, "result": asdict(verify(lines[:i] + lines[i + 1:]))}
                for i in range(len(lines))]
    shortened = []
    for i, line in enumerate(lines):
        if len(line.cells) <= 2:
            continue
        for end, cells in (("bulb", line.cells[1:]), ("tip", line.cells[:-1])):
            trial = list(lines)
            trial[i] = Line(line.kind, cells, line.difference)
            shortened.append({"line": i + 1, "removed_end": end, "result": asdict(verify(trial))})
    return {"full": asdict(full), "orientations": orientations,
            "without_island_rule": asdict(verify(lines, island=False)),
            "without_each_line": removals, "shortened_lines": shortened,
            "human_difficulty": "Not established by the uniqueness search."}


def render_svg(
    lines: Sequence[Line], title: str = "Even Island", *,
    solution: Sequence[Sequence[int]] | None = None,
) -> str:
    """Render a standalone English puzzle or a separately labeled solution card."""
    from html import escape

    if solution is not None and not validate_solution(solution, lines):
        raise ValueError("Cannot render an invalid solution")
    left, top, step = 72, 88, 64

    def point(cell: int) -> tuple[int, int]:
        return left + (cell % 9) * step + step // 2, top + (cell // 9) * step + step // 2

    heading = title + (" - Solution" if solution is not None else "")
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="720" height="860" viewBox="0 0 720 860">',
             f'<title>{escape(heading)}</title>',
             '<rect width="720" height="860" fill="white"/>',
             f'<text x="360" y="38" text-anchor="middle" font-family="sans-serif" font-size="27" fill="#172433">{escape(heading)}</text>',
             '<text x="360" y="64" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#536170">Connected-even Sudoku</text>']
    if solution is not None:
        for r, row in enumerate(solution):
            for c, digit in enumerate(row):
                if digit % 2 == 0:
                    parts.append(f'<rect class="even-cell" x="{left + c * step}" y="{top + r * step}" width="{step}" height="{step}" fill="#e8f0f6"/>')
    for i in range(10):
        width = 3 if i % 3 == 0 else 1
        x, y = left + step * i, top + step * i
        parts.append(f'<path d="M {left} {y} H {left + 9 * step} M {x} {top} V {top + 9 * step}" stroke="#333" stroke-width="{width}"/>')
    for line in lines:
        color = "#c4ccd4" if line.kind == "thermometer" else "#79b986"
        points = " ".join(f"{x},{y}" for x, y in map(point, line.cells))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>')
        if line.kind == "thermometer":
            x, y = point(line.cells[0])
            parts.append(f'<circle cx="{x}" cy="{y}" r="18" fill="{color}"/>')
    if solution is not None:
        for r, row in enumerate(solution):
            for c, digit in enumerate(row):
                x, y = point(r * 9 + c)
                parts.append(f'<text class="digit" x="{x - 8}" y="{y + 10}" font-family="Helvetica" font-size="29" fill="#172433">{digit}</text>')
    rules = ["Place 1-9 once in every row, column and 3x3 box.",
             "All cells containing 2, 4, 6 or 8 form one side-connected island."]
    if any(line.kind == "thermometer" for line in lines):
        rules.append("Digits strictly increase from each thermometer bulb to its tip.")
    if any(line.kind == "whisper" for line in lines):
        differences = {line.difference for line in lines if line.kind == "whisper"}
        if len(differences) != 1:
            raise ValueError("SVG rendering requires a single common whisper difference")
        rules.append(f"On green lines, adjacent digits differ by at least {differences.pop()}.")
    for i, rule in enumerate(rules):
        parts.append(f'<text x="72" y="{704 + 24 * i}" font-family="sans-serif" font-size="15" fill="#172433">{escape(rule)}</text>')
    note = "Solution card. Shaded cells contain even digits." if solution is not None else "No given digits. Diagonal contact never joins even cells."
    parts.append('<text x="72" y="810" font-family="sans-serif" font-size="13" fill="#536170">Thermometer segments may run diagonally.</text>')
    parts.append(f'<text x="72" y="834" font-family="sans-serif" font-size="13" fill="#536170">{note}</text>')
    return "\n".join(parts + ["</svg>", ""])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    analysis = sub.add_parser("analyze", help="count all unrestricted connected-even Sudokus")
    analysis.add_argument("--json", type=Path)
    verification = sub.add_parser("verify", help="verify a zero-given line puzzle")
    verification.add_argument("puzzle", type=Path)
    verification.add_argument("--timeout", type=float)
    verification.add_argument("--limit", type=int, default=2, help="stop after this many solutions (default: 2)")
    verification.add_argument("--without-island", action="store_true")
    verification.add_argument("--audit", action="store_true", help="also remove each line, shorten endpoints and test all orientations")
    verification.add_argument("--json", type=Path)
    render = sub.add_parser("render", help="render a blank puzzle to SVG")
    render.add_argument("puzzle", type=Path)
    render.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            report = analyze_freedom()
            print(f"Exact count: {report['total_grids']:,} Sudokus across {report['orientations']} orientations")
            print(f"Even normalized: {report['even_layer']['normalized_count']}; odd normalized: {report['odd_layer']['normalized_count']}")
        else:
            data, lines = load_puzzle(args.puzzle)
            if args.command == "render":
                args.output.write_text(render_svg(lines, data.get("title", "Even Island")), encoding="utf-8")
                print(f"Wrote blank puzzle to {args.output}")
                return 0
            if args.audit and (args.timeout is not None or args.without_island or args.limit != 2):
                raise ValueError("--audit uses its own comparisons; do not combine it with --timeout, --limit or --without-island")
            report = audit(lines) if args.audit else asdict(verify(
                lines, island=not args.without_island, timeout=args.timeout, limit=args.limit,
            ))
            outcome = report["full"] if args.audit else report
            print(f"{outcome['status']}: {len(outcome['solutions'])} solution(s) found; exhaustive={outcome['exhaustive']}")
        if args.json:
            args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 2 if args.command == "verify" and outcome["status"] == "UNKNOWN" else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
