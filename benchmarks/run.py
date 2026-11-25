"""Reproducible, isolated local benchmark of the printed puzzle statements."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
import tempfile
from time import perf_counter

from benchmarks.solve import METHODS
from island_puzzles import load_parity, load_puzzle, validate_solution

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("benchmarks/solve.py", "benchmarks/run.py", "island_puzzles.py",
           "sudoku_completion.py", "sudoku_island.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def processor_name() -> str:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def median_metric(rows, key):
    return median(row[key] for row in rows)


def render_report(report: dict) -> str:
    trials, budget = report["trials"], report["configuration"]["seconds"]
    count = report["configuration"]["repeats"]
    env = report["environment"]
    lines = [
        "# Rule-only solver benchmark", "",
        "These solvers receive only each published `puzzle.json`: Sudoku rules,",
        "line clues, printed parity marks and orthogonal even-cell connectivity.",
        "They do **not** receive the island theorem, eight orientations, a fixed",
        "parity mask, the expected filling or construction/removal certificates.", "",
        f"Recorded at {report['recorded_at_utc']}. {count} fresh-process runs per cell,",
        f"a {budget:g} s wall-time budget per run, sequential execution, shuffled order",
        "with seed 0. Values below are medians; raw trials include all counters.",
        "The search first seeks one solution, then continues to prove uniqueness.",
        "The uniqueness time includes the first-solution phase.", "",
        f"Environment: {env['platform']}; Python {env['python']};",
        f"{env['processor']}; {env['logical_cpus']} logical CPUs.",
        f"Z3: {report.get('z3_version') or 'not used'}. Each worker uses one solver thread.", "",
        "| Puzzle | Method | First solution (s) | Uniqueness | Search work | Peak MiB | CPU s |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for puzzle in report["puzzles"]:
        for method in report["configuration"]["methods"]:
            rows = [row for row in trials if row["puzzle"] == puzzle["path"] and row["method"] == method]
            found = [row["first_solution_seconds"] for row in rows if row["first_solution_seconds"] is not None]
            first = f"{median(found):.3f} ({len(found)}/{count})" if found else f">{budget:g} (0/{count})"
            statuses = {row["status"] for row in rows}
            if statuses == {"UNIQUE"}:
                proof = f"{median_metric(rows, 'elapsed_seconds'):.3f} s ({count}/{count})"
            elif statuses == {"UNKNOWN"}:
                proof = f"UNKNOWN at {budget:g} s"
            else:
                proof = ", ".join(f"{s}: {sum(r['status']==s for r in rows)}/{count}" for s in sorted(statuses))
            if method.startswith("csp"):
                work = f"{median(r['metrics']['states'] for r in rows):,.0f} nodes"
            else:
                work = f"{median(r['metrics'].get('engine_statistics', {}).get('sat decisions', 0) for r in rows):,.0f} decisions"
            memory = [row["peak_process_mib"] for row in rows if row["peak_process_mib"] is not None]
            peak = f"{median(memory):.1f}" if memory else "n/a"
            lines.append(f"| {puzzle['title']} | `{method}` | {first} | {proof} | {work} | {peak} | {median_metric(rows, 'cpu_seconds'):.2f} |")
    lines += ["", "## Reading the results", ""]
    if all(row["status"] == "UNKNOWN" and not row["solutions"] for row in trials):
        lines += [
            f"**No tested method found a solution within {budget:g} seconds in any trial.**",
            "Every uniqueness result is therefore UNKNOWN. These are censored timings:",
            f"the observed time to first solution and proof exceeds {budget:g} seconds,",
            "but this experiment gives no completed solve times or ranking of the four",
            "puzzles. It also says nothing about how long an extended run would take.", "",
        ]
    lines += [
        "UNKNOWN means the search was interrupted, not that the puzzle has no",
        "solution or that uniqueness failed. The existing exhaustive theorem-based",
        "audits remain separate evidence; they are deliberately excluded here.", "",
        "CSP nodes are calls to the recursive search, including branches that fail",
        "during propagation. SAT decisions are internal Boolean choices. They are",
        "**not comparable units**; compare work only within the same method.",
        "More nodes in a timed-out run can simply mean cheaper nodes, rather than",
        "a closer approach to a solution. Rejected disconnected grids are not puzzle",
        "solutions. SAT statistics are the engine's cumulative counters at the final",
        "incremental check; `sat_calls` counts those checks, including the last timeout.", "",
        "Peak memory is the process high-water resident working set (MiB), including",
        "the interpreter, imports and native Z3 allocations. It is not just search",
        "data, nor a sampling-based estimate. Wall/CPU timings include model setup",
        "and propagation-table construction, exclude process startup and JSON input",
        "parsing, and include Z3 import/setup for SAT. Parent-observed process duration",
        "is also saved in the raw results. Limits are cooperative, with a 10 s hard",
        "kill grace; any overrun is reported in actual elapsed time.", "",
        "This is a small local automatic-search benchmark, **not a human difficulty",
        "rating**, a comparison of languages, or a claim about the best possible",
        "Sudoku/constraint solvers. Two CSP configurations share an implementation;",
        "the SAT encoding uses a different search engine. Repetitions share the same",
        "deterministic search order and measure local timing variation, not seed variation.", "",
        "See [methodology and commands](README.md), [raw results](results.json) and",
        "[per-trial CSV](results.csv). Puzzle and solver-source SHA-256 hashes are",
        "recorded in the JSON (source hashes normalize CRLF to LF).", "",
    ]
    return "\n".join(lines)


def run(args) -> dict:
    puzzles = []
    for path in args.puzzles:
        path = path.resolve()
        data, _ = load_puzzle(path)
        puzzles.append({"path": path.relative_to(ROOT).as_posix(), "title": data["title"],
                        "sha256_lf": digest(path)})
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    report = {"schema_version": 1, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_base_revision": revision, "source_worktree_dirty": dirty,
              "source_sha256_lf": {name: digest(ROOT / name) for name in SOURCES},
              "configuration": {"seconds": args.seconds, "repeats": args.repeats,
                                "methods": list(args.methods), "order_seed": 0,
                                "parallel_workers": 1, "python_hash_seed": 0},
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "processor": processor_name(), "logical_cpus": os.cpu_count()},
              "puzzles": puzzles, "trials": []}
    rng = random.Random(0)
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = []
    for repeat in range(args.repeats):
        round_jobs = [(puzzle, method, repeat+1) for puzzle in puzzles for method in args.methods]
        rng.shuffle(round_jobs)
        jobs.extend(round_jobs)
    with tempfile.TemporaryDirectory(prefix="island-benchmark-") as temporary:
        for index, (puzzle, method, repeat) in enumerate(jobs, 1):
            print(f"[{index}/{len(jobs)}] {puzzle['title']} / {method} / repeat {repeat}", flush=True)
            output = Path(temporary) / "trial.json"
            output.unlink(missing_ok=True)
            command = [sys.executable, "-m", "benchmarks.solve", puzzle["path"],
                       "--method", method, "--seconds", str(args.seconds), "--output", str(output)]
            started = perf_counter()
            try:
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                           env={**os.environ, "PYTHONHASHSEED": "0"},
                                           timeout=args.seconds+10, check=True)
            except subprocess.TimeoutExpired as exc:
                # subprocess.run kills and waits for its own worker before raising.
                raise RuntimeError(f"Worker exceeded hard limit: {command}") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(f"Worker failed: {exc.stderr}") from exc
            if completed.stdout.strip() or completed.stderr.strip():
                raise RuntimeError(f"Unexpected worker output: {completed.stdout}\n{completed.stderr}")
            row = json.loads(output.read_text(encoding="utf-8"))
            row.update(puzzle=puzzle["path"], repeat=repeat, process_wall_seconds=perf_counter()-started)
            # Post-run validation only. The worker never reads solution.json.
            data, lines = load_puzzle(ROOT / puzzle["path"])
            for encoded in row["solutions"]:
                grid = tuple(tuple(map(int, encoded[r*9:r*9+9])) for r in range(9))
                if not validate_solution(grid, lines, parity=load_parity(data)):
                    raise RuntimeError("Post-run rule validation failed")
            report["trials"].append(row)
            if row["engine_version"]:
                report["z3_version"] = row["engine_version"]
            # Save after every completed trial, so partial runs remain inspectable.
            (args.output / "results.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
            memory = row['peak_process_mib']
            memory_text = f"{memory:.1f} MiB" if memory is not None else "memory unavailable"
            print(f"  {row['status']}, {len(row['solutions'])} witness(es), {row['elapsed_seconds']:.3f} s, "
                  f"{memory_text}", flush=True)
    for name, expected in report["source_sha256_lf"].items():
        if digest(ROOT / name) != expected:
            raise RuntimeError(f"Solver source changed during the benchmark: {name}")
    for puzzle in puzzles:
        if digest(ROOT / puzzle["path"]) != puzzle["sha256_lf"]:
            raise RuntimeError("Puzzle changed during the benchmark")
    (args.output / "report.md").write_text(render_report(report), encoding="utf-8")
    buffer = io.StringIO(newline="")
    fields = ("puzzle", "method", "repeat", "status", "exhaustive", "elapsed_seconds", "cpu_seconds",
              "first_solution_seconds", "first_solution_states", "peak_process_mib", "process_wall_seconds",
              "states", "sat_decisions", "sat_conflicts", "sat_calls", "connectivity_checks", "connectivity_cuts",
              "rejected_complete_grids", "solution_count")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in report["trials"]:
        flat = {key: row.get(key) for key in fields}
        flat.update({key: row["metrics"].get(key) for key in fields if key in row["metrics"]})
        engine = row["metrics"].get("engine_statistics", {})
        flat.update(sat_decisions=engine.get("sat decisions"), sat_conflicts=engine.get("sat conflicts"),
                    solution_count=len(row["solutions"]))
        writer.writerow(flat)
    (args.output / "results.csv").write_bytes(buffer.getvalue().replace("\r\n", "\n").encode())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", nargs="+", type=Path,
                        default=sorted((ROOT / "constructions").glob("even_island_*/puzzle.json")))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=METHODS)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0 or args.repeats < 1:
        parser.error("Use a positive finite time budget and at least one repeat")
    if len(set(args.methods)) != len(args.methods):
        parser.error("Methods cannot be repeated")
    run(args)


if __name__ == "__main__":
    main()
