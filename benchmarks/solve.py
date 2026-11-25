"""Rule-only solvers: no island masks, orientation theorem or solution input.

Only parsing, ordinary Sudoku/line propagation and the whole-grid checker are
shared with the construction tools. Z3 is optional and imported only by SAT.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from time import perf_counter, process_time

from island_puzzles import (
    ALL_DIGITS, EVEN, ODD, UNITS, _enumerate, load_parity, load_puzzle,
    validate_solution,
)

METHODS = ("csp-leaf", "csp-graph", "sat-cuts")
NEIGHBORS = tuple(tuple(j for j in range(81)
                        if abs(i // 9 - j // 9) + abs(i % 9 - j % 9) == 1)
                  for i in range(81))


def components(cells: set[int], neighbors=NEIGHBORS) -> list[set[int]]:
    remaining = cells.copy()
    result = []
    while remaining:
        reached = {remaining.pop()}
        pending = list(reached)
        while pending:
            for other in neighbors[pending.pop()]:
                if other in remaining:
                    remaining.remove(other)
                    reached.add(other)
                    pending.append(other)
        result.append(reached)
    return result


def required_bridges(possible: set[int], required: set[int], neighbors=NEIGHBORS) -> set[int]:
    """Unknown articulation vertices needed to connect all mandatory vertices.

    Each component must already contain either all mandatory vertices or none.
    A DFS subtree separated by deleting v forces v iff mandatory vertices lie
    both in that subtree and outside it. This also handles the DFS root.
    """
    if len(required) < 2:
        return set()
    discovered, low, count = {}, {}, {}
    forced = set()

    def visit(cell: int, parent: int | None) -> None:
        discovered[cell] = low[cell] = len(discovered)
        count[cell] = int(cell in required)
        for other in neighbors[cell]:
            if other not in possible or other == parent:
                continue
            if other in discovered:
                low[cell] = min(low[cell], discovered[other])
                continue
            visit(other, cell)
            count[cell] += count[other]
            low[cell] = min(low[cell], low[other])
            if low[other] >= discovered[cell] and 0 < count[other] < len(required):
                if cell not in required:
                    forced.add(cell)

    visit(min(required), None)
    return forced


def connectivity_filter(domains: list[int], stats: dict[str, int]) -> bool:
    """Sound necessary conditions derived directly from the printed rules.

    Every Sudoku unit contains four even digits. The final 36-cell island must
    fit in one component of the possible-even graph, contain all required-even
    cells and contain at least four cells of every unit. Mandatory articulation
    cells must also be even. None of these tests prescribes an island shape.
    """
    stats["connectivity_checks"] += 1
    for unit in UNITS:
        possible = [cell for cell in unit if domains[cell] & EVEN]
        required = [cell for cell in unit if not domains[cell] & ODD]
        if len(possible) < 4 or len(required) > 4:
            return False
        if len(required) == 4:
            for cell in possible:
                if domains[cell] & ODD:
                    domains[cell] &= ODD
        elif len(possible) == 4:
            for cell in possible:
                domains[cell] &= EVEN
    possible = {cell for cell, domain in enumerate(domains) if domain & EVEN}
    required = {cell for cell, domain in enumerate(domains) if not domain & ODD}
    viable = [part for part in components(possible)
              if len(part) >= 36 and required <= part
              and all(len(part.intersection(unit)) >= 4 for unit in UNITS)]
    if not viable:
        return False
    allowed = set().union(*viable)
    for cell in possible - allowed:
        domains[cell] &= ODD
    for cell in required_bridges(allowed, required):
        domains[cell] &= EVEN
    return all(domains)


def peak_memory_mib() -> float | None:
    """Peak resident process memory, including interpreter/imports/native Z3."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        memory = Counters()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb):
            return None
        return memory.PeakWorkingSetSize / (1024 ** 2)
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value / (1024 ** 2 if sys.platform == "darwin" else 1024)
    except (ImportError, OSError):
        return None


class EnoughSolutions(Exception):
    pass


def solve(path: Path, method: str, seconds: float) -> dict:
    """Find a witness, then continue the same search until unique/multiple/timeout.

    The only input file opened is puzzle.json. An expected solution is never
    passed here. All witness grids are checked from the rules before returning.
    """
    if method not in METHODS or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Expected a known method and a positive finite time budget")
    data, lines = load_puzzle(path)
    parity = load_parity(data)
    started, cpu_started = perf_counter(), process_time()
    deadline = started + seconds
    stats = {"states": 0, "connectivity_checks": 0, "rejected_complete_grids": 0}
    solutions = []
    first_seconds = first_states = None
    exhaustive, reason = False, ""
    engine_version = None

    def accept(digits: tuple[int, ...]) -> None:
        nonlocal first_seconds, first_states
        grid = tuple(tuple(digits[9*r:9*r+9]) for r in range(9))
        if not validate_solution(grid, lines, parity=parity):
            raise RuntimeError("Independent rule validator rejected a witness")
        encoded = "".join(map(str, digits))
        if encoded in solutions:
            raise RuntimeError("Duplicate solution generated")
        solutions.append(encoded)
        if first_seconds is None:
            first_seconds = perf_counter() - started
            first_states = stats["states"] if method.startswith("csp") else None
        if len(solutions) == 2:
            raise EnoughSolutions

    try:
        if method.startswith("csp"):
            domains = [ALL_DIGITS] * 81
            for mark in parity:
                domains[mark.cell] &= EVEN if mark.even else ODD

            def leaf(digits):
                stats["connectivity_checks"] += 1
                even_cells = {i for i, digit in enumerate(digits) if digit % 2 == 0}
                if len(components(even_cells)) == 1:
                    accept(digits)
                else:
                    stats["rejected_complete_grids"] += 1

            _enumerate(domains, tuple((unit, ALL_DIGITS) for unit in UNITS),
                       lines, leaf, stats, deadline,
                       (lambda d: connectivity_filter(d, stats)) if method == "csp-graph" else None)
            exhaustive = True
        else:
            import z3

            engine_version = z3.get_version_string()
            engine = z3.SolverFor("QF_FD")
            engine.set(random_seed=0, threads=1)
            x = [[z3.Bool(f"x_{cell}_{digit}") for digit in range(1, 10)] for cell in range(81)]
            even = [z3.Bool(f"even_{cell}") for cell in range(81)]
            for cell in range(81):
                engine.add(z3.PbEq([(v, 1) for v in x[cell]], 1))
                engine.add(even[cell] == z3.Or([x[cell][d-1] for d in (2, 4, 6, 8)]))
            for unit in UNITS:
                for digit in range(9):
                    engine.add(z3.PbEq([(x[cell][digit], 1) for cell in unit], 1))
            for mark in parity:
                engine.add(even[mark.cell] if mark.even else z3.Not(even[mark.cell]))
            for line in lines:
                if line.kind == "renban":
                    engine.add(z3.Or([
                        z3.And([z3.Or(x[cell][low:low+len(line.cells)]) for cell in line.cells])
                        for low in range(10-len(line.cells))]))
                    pairs = [(a, b) for i, a in enumerate(line.cells) for b in line.cells[i+1:]]
                    forbidden = [(d, d) for d in range(9)]
                else:
                    pairs = list(zip(line.cells, line.cells[1:]))
                    forbidden = [(a, b) for a in range(9) for b in range(9)
                                 if (a >= b if line.kind == "thermometer"
                                     else abs(a-b) < line.difference)]
                for a, b in pairs:
                    engine.add([z3.Or(z3.Not(x[a][da]), z3.Not(x[b][db])) for da, db in forbidden])
            stats.update(sat_calls=0, connectivity_cuts=0)
            while True:
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    raise TimeoutError
                engine.set(timeout=max(1, int(remaining * 1000)))
                stats["sat_calls"] += 1
                answer = engine.check()
                # Z3 counters are cumulative across incremental checks.
                stats["engine_statistics"] = {key: value for key, value in engine.statistics()}
                if answer == z3.unsat:
                    exhaustive = True
                    break
                if answer != z3.sat:
                    reason = engine.reason_unknown()
                    break
                model = engine.model()
                digits = tuple(next(d+1 for d in range(9) if z3.is_true(model.eval(x[cell][d])))
                               for cell in range(81))
                parts = components({i for i, d in enumerate(digits) if d % 2 == 0})
                stats["connectivity_checks"] += 1
                if len(parts) == 1:
                    accept(digits)
                    engine.add(z3.Or([z3.Not(x[cell][d-1]) for cell, d in enumerate(digits)]))
                else:
                    stats["rejected_complete_grids"] += 1
                    for part in parts:
                        boundary = set().union(*(set(NEIGHBORS[cell]) for cell in part)) - part
                        # |part| < 36. If every cell in part stays even, a connected
                        # 36-cell island must use at least one boundary cell.
                        engine.add(z3.Or([z3.Not(even[cell]) for cell in sorted(part)]
                                         + [even[cell] for cell in sorted(boundary)]))
                        stats["connectivity_cuts"] += 1
    except EnoughSolutions:
        reason = "Two independently validated solutions found."
    except TimeoutError:
        reason = "Wall-time budget exhausted."
    status = ("MULTIPLE" if len(solutions) >= 2 else "UNKNOWN" if not exhaustive
              else "UNIQUE" if solutions else "UNSAT")
    return {"method": method, "title": data["title"], "status": status,
            "exhaustive": exhaustive, "reason": reason or "Search exhausted.",
            "budget_seconds": seconds, "elapsed_seconds": perf_counter()-started,
            "cpu_seconds": process_time()-cpu_started, "first_solution_seconds": first_seconds,
            "first_solution_states": first_states, "solutions": solutions, "metrics": stats,
            "peak_process_mib": peak_memory_mib(), "engine_version": engine_version}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzle", type=Path)
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = solve(args.puzzle, args.method, args.seconds)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
