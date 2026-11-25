"""Detached rule-only SAT campaign with saved progress and separate phase budgets."""

from __future__ import annotations

import argparse
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output/sat-campaign"
SOURCES = ("benchmarks/campaign.py", "benchmarks/solve.py", "island_puzzles.py",
           "sudoku_completion.py", "sudoku_island.py")
SAT_METHODS = ("sat-cuts", "sat-tree")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(text.encode("utf-8"))
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def save_json(path: Path, data: dict) -> None:
    atomic_text(path, json.dumps(data, indent=2)+"\n")


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # A restricted observer can be denied access to a live process.
            # Windows reports ERROR_INVALID_PARAMETER for a nonexistent PID;
            # ERROR_ACCESS_DENIED must not be mistaken for process death.
            return ctypes.get_last_error() == 5
        code = wintypes.DWORD()
        try:
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return ctypes.get_last_error() == 5
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def prepare(output: Path, solution_seconds: float, proof_seconds: float,
            workers: int, methods: list[str]) -> dict:
    """Freeze code and statements, never solution files or theorem outputs."""
    output.mkdir(parents=True, exist_ok=True)
    existing = read_json(output / "campaign.json")
    if existing:
        return existing
    snapshot = output / "snapshot"
    hashes = {}
    for name in SOURCES:
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        destination.write_bytes(source)
        hashes[name] = hashlib.sha256(source).hexdigest()
    jobs = []
    for path in sorted((ROOT / "constructions").glob("even_island_*/puzzle.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        relative = f"inputs/{path.parent.name}.json"
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = path.read_bytes().replace(b"\r\n", b"\n")
        destination.write_bytes(source)
        for method in methods:
            jobs.append({"id": f"{path.parent.name}--{method}", "title": data["title"],
                         "puzzle": relative, "original_puzzle": path.relative_to(ROOT).as_posix(),
                         "puzzle_sha256_lf": hashlib.sha256(source).hexdigest(),
                         "method": method, "state": "PENDING", "pid": None})
    # Start all original SAT-cut jobs first; two different puzzles run at once.
    jobs.sort(key=lambda job: (methods.index(job["method"]), job["id"]))
    if not jobs:
        raise ValueError("No published puzzles found")
    state = {"schema_version": 1, "created_at_utc": utc(), "status": "PREPARED",
             "configuration": {"solution_seconds": solution_seconds, "proof_seconds": proof_seconds,
                               "workers": workers, "methods": methods, "solver_threads": 1, "seed": 0},
             "environment": {"python": platform.python_version(), "platform": platform.platform(),
                             "executable": sys.executable, "processor": platform.processor(),
                             "logical_cpus": os.cpu_count()},
             "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             "source_sha256_lf": hashes, "controller_pid": None, "jobs": jobs}
    save_json(output / "campaign.json", state)
    return state


def check_snapshot(output: Path, state: dict) -> None:
    for name, expected in state["source_sha256_lf"].items():
        if hashlib.sha256((output / "snapshot" / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen source changed: {name}")
    for job in state["jobs"]:
        if hashlib.sha256((output / "snapshot" / job["puzzle"]).read_bytes()).hexdigest() != job["puzzle_sha256_lf"]:
            raise RuntimeError(f"Frozen statement changed: {job['puzzle']}")


def start(args) -> None:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / "launch.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(descriptor)
        state = prepare(output, args.solution_seconds, args.proof_seconds, args.workers, args.methods)
        configuration = state["configuration"]
        print(f"Budgets per job: first solution {configuration['solution_seconds']:g} s; "
              f"additional uniqueness search {configuration['proof_seconds']:g} s.")
        if pid_alive(state.get("controller_pid")):
            print(f"Campaign already running (controller PID {state['controller_pid']}).")
            return
        if any(pid_alive(job.get("pid")) for job in state["jobs"] if job["state"] == "RUNNING"):
            raise RuntimeError("An orphan worker is still running; do not start duplicate searches")
        if state["status"] in ("FINISHED", "FINISHED_WITH_ERRORS"):
            print("Campaign is already complete. Use a different --output directory for a new run.")
            return
        check_snapshot(output, state)
        (output / "stop.request").unlink(missing_ok=True)
        command = [sys.executable, "-u", "-m", "benchmarks.campaign", "serve", "--output", str(output)]
        options = {"cwd": output / "snapshot", "env": {**os.environ, "PYTHONHASHSEED": "0"}}
        with (output / "controller.log").open("ab", buffering=0) as log:
            if sys.platform == "win32":
                flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                try:
                    process = subprocess.Popen(command, stdout=log, stderr=log,
                                               creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
                except PermissionError:
                    process = subprocess.Popen(command, stdout=log, stderr=log, creationflags=flags, **options)
            else:
                process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True, **options)
        for _ in range(100):
            current = read_json(output / "campaign.json")
            if current.get("controller_pid") == process.pid and current["status"] != "PREPARED":
                break
            if process.poll() is not None:
                raise RuntimeError(f"Controller exited during startup; see {output / 'controller.log'}")
            time.sleep(0.1)
        else:
            raise RuntimeError(f"Controller did not report startup; inspect {output / 'controller.log'}")
        print(f"Launched detached campaign controller PID {process.pid}.")
        print(f"Progress: {output / 'status.md'}")
        print("Open campaign_status.bat to watch; closing that window does not stop the campaign.")
    finally:
        lock.unlink(missing_ok=True)


def progress_for(output: Path, job: dict) -> dict:
    return (read_json(output / f"{job['id']}.result.json")
            or read_json(output / f"{job['id']}.progress.json") or {})


def rows_for(output: Path, state: dict) -> list[dict]:
    rows = []
    for job in state["jobs"]:
        progress = progress_for(output, job)
        active = job["state"] == "RUNNING"
        age = max(0, time.time()-progress.get("saved_at_epoch", time.time())) if active else 0
        first = progress.get("first_solution_seconds")
        proof = progress.get("uniqueness_search_seconds")
        if active and proof is not None:
            proof += age
        rows.append({"id": job["id"], "title": job["title"], "method": job["method"],
                     "state": job["state"], "status": progress.get("status", job["state"]),
                     "phase": progress.get("phase", "not_started"),
                     "elapsed_seconds": progress.get("elapsed_seconds", 0)+age,
                     "first_solution_seconds": first, "uniqueness_search_seconds": proof,
                     "peak_process_mib": progress.get("peak_process_mib"),
                     "sat_calls": progress.get("metrics", {}).get("sat_calls"),
                     "sat_decisions": progress.get("metrics", {}).get("engine_statistics", {}).get("sat decisions"),
                     "solution_count": len(progress.get("solutions", []))})
    return rows


def duration(value) -> str:
    return "-" if value is None else f"{value:.1f} s"


def render_status(output: Path, state: dict) -> str:
    rows = rows_for(output, state)
    live = pid_alive(state.get("controller_pid"))
    completed = sum(row["state"] in ("FINISHED", "FAILED", "CANCELLED") for row in rows)
    label = state["status"]
    if label == "RUNNING" and not live:
        label = "INTERRUPTED (controller is not running)"
    lines = ["# Offline SAT campaign", "", f"State: **{label}**. Completed jobs: **{completed}/{len(rows)}**.",
             f"Controller PID: {state.get('controller_pid')}; alive: {live}. Updated: {utc()}.", "",
             "| Puzzle | SAT | State / phase | Elapsed | First solution | Additional uniqueness search | Last decisions | Peak MiB |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        label = row["status"] if row["state"] == "FINISHED" else row["state"]
        if row["state"] == "RUNNING":
            label += " / " + row["phase"]
        memory = "-" if row["peak_process_mib"] is None else f"{row['peak_process_mib']:.1f}"
        lines.append(f"| {row['title']} | {row['method']} | {label} | {duration(row['elapsed_seconds'])} | "
                     f"{duration(row['first_solution_seconds'])} | {duration(row['uniqueness_search_seconds'])} | "
                     f"{row['sat_decisions'] if row['sat_decisions'] is not None else '-'} | {memory} |")
    lines += ["", "Live elapsed times are estimates; completed timings are measured inside each worker.",
              "Decisions and memory are saved snapshots, updated between SAT calls; a long native",
              "SAT call can advance while these counters remain unchanged. The controller heartbeat",
              "continues every two seconds. RUNNING is not a result; UNKNOWN is an interrupted search.",
              "Additional uniqueness time is measured after finding the first solution. It is a proof",
              "time only when status is UNIQUE (or a second-witness search when MULTIPLE).", "",
              "Frozen code and statement hashes: campaign.json. Per-job progress/results: *.json.",
              "Readable table: status.md. Machine-readable table: summary.csv.", ""]
    return "\n".join(lines)


def save_status(output: Path, state: dict) -> None:
    state["heartbeat_at_utc"] = utc()
    save_json(output / "campaign.json", state)
    atomic_text(output / "status.md", render_status(output, state))
    rows = rows_for(output, state)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(output / "summary.csv", buffer.getvalue().replace("\r\n", "\n"))


def serve(output: Path) -> None:
    state = read_json(output / "campaign.json")
    check_snapshot(output, state)
    if pid_alive(state.get("controller_pid")) and state["controller_pid"] != os.getpid():
        raise RuntimeError("A campaign controller is already running")
    state.update(status="RUNNING", controller_pid=os.getpid(), last_started_at_utc=utc())
    for job in state["jobs"]:
        if job["state"] in ("RUNNING", "CANCELLED", "FAILED"):
            job.update(state="PENDING", pid=None)
    awake = False
    if sys.platform == "win32":
        awake = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
    state["automatic_sleep_prevented"] = awake
    active = {}
    try:
        while True:
            stopping = (output / "stop.request").exists()
            for identifier, (process, job, launched) in list(active.items()):
                progress = progress_for(output, job)
                # Native check timeout + 60 s grace. Restarting a dead process
                # cannot restore Z3 learnt clauses; interrupted jobs restart fresh.
                allowance = state["configuration"]["solution_seconds"]
                if progress.get("first_solution_seconds") is not None:
                    allowance = progress["first_solution_seconds"] + state["configuration"]["proof_seconds"]
                if process.poll() is None and (stopping or time.monotonic()-launched > allowance+60):
                    process.terminate()
                    process.wait(timeout=10)
                    job["state"] = "CANCELLED" if stopping else "FAILED"
                    job["error"] = "Stop requested" if stopping else "Worker exceeded deadline grace"
                if process.poll() is not None:
                    if job["state"] == "RUNNING":
                        result = read_json(output / f"{identifier}.result.json")
                        job["state"] = "FINISHED" if process.returncode == 0 and result else "FAILED"
                        if job["state"] == "FAILED":
                            job["error"] = f"Worker exit {process.returncode}; see {identifier}.log"
                    job["finished_at_utc"] = utc()
                    print(f"{utc()} finished {identifier}: {job['state']}", flush=True)
                    del active[identifier]
            if stopping:
                state["status"] = "STOPPED"
                save_status(output, state)
                return
            while len(active) < state["configuration"]["workers"]:
                job = next((job for job in state["jobs"] if job["state"] == "PENDING"), None)
                if job is None:
                    break
                identifier = job["id"]
                for suffix in (".progress.json", ".result.json"):
                    (output / f"{identifier}{suffix}").unlink(missing_ok=True)
                command = [sys.executable, "-u", "-m", "benchmarks.campaign", "worker",
                           "--output", str(output), "--job", identifier]
                with (output / f"{identifier}.log").open("ab", buffering=0) as log:
                    process = subprocess.Popen(command, cwd=output / "snapshot", stdout=log, stderr=log,
                                               env={**os.environ, "PYTHONHASHSEED": "0"})
                job.update(state="RUNNING", pid=process.pid, started_at_utc=utc())
                active[identifier] = (process, job, time.monotonic())
                print(f"{utc()} started {identifier}, PID {process.pid}", flush=True)
            if not active and not any(job["state"] == "PENDING" for job in state["jobs"]):
                state["status"] = "FINISHED_WITH_ERRORS" if any(j["state"] == "FAILED" for j in state["jobs"]) else "FINISHED"
                state["finished_at_utc"] = utc()
                save_status(output, state)
                return
            save_status(output, state)
            time.sleep(2)
    except BaseException:
        # A controlled shutdown never leaves managed workers running invisibly.
        for process, job, _ in active.values():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            job["state"] = "CANCELLED"
        state["status"] = "INTERRUPTED"
        save_status(output, state)
        raise
    finally:
        if awake:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def worker(output: Path, identifier: str) -> None:
    from benchmarks.solve import solve

    state = read_json(output / "campaign.json")
    job = next(job for job in state["jobs"] if job["id"] == identifier)
    check_snapshot(output, state)

    def progress(data):
        data = {**data, "saved_at_utc": utc(), "saved_at_epoch": time.time()}
        save_json(output / f"{identifier}.progress.json", data)

    result = solve(output / "snapshot" / job["puzzle"], job["method"],
                   state["configuration"]["solution_seconds"],
                   proof_seconds=state["configuration"]["proof_seconds"], progress=progress)
    result.update(saved_at_utc=utc(), saved_at_epoch=time.time())
    save_json(output / f"{identifier}.result.json", result)


def status(args) -> None:
    try:
        while True:
            state = read_json(args.output / "campaign.json")
            if state is None:
                print("No campaign here. Run start_campaign.bat first.")
                return
            if args.watch and sys.stdout.isatty():
                os.system("cls" if sys.platform == "win32" else "clear")
            print(render_status(args.output, state), flush=True)
            if not args.watch or state["status"] != "RUNNING" or not pid_alive(state.get("controller_pid")):
                return
            time.sleep(5)
    except KeyboardInterrupt:
        print("Closed status viewer. The campaign continues in the background.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "serve", "worker", "status", "stop"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        if name == "start":
            command.add_argument("--solution-seconds", type=float, default=1800)
            command.add_argument("--proof-seconds", type=float, default=1800)
            command.add_argument("--workers", type=int, default=2)
            command.add_argument("--methods", nargs="+", choices=SAT_METHODS, default=list(SAT_METHODS))
        if name == "worker":
            command.add_argument("--job", required=True)
        if name == "status":
            command.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.command == "start":
        import math
        if (not all(math.isfinite(v) and v > 0 for v in (args.solution_seconds, args.proof_seconds))
                or not 1 <= args.workers <= 4 or len(set(args.methods)) != len(args.methods)):
            parser.error("Use positive finite budgets, 1..4 workers and distinct methods")
        start(args)
    elif args.command == "serve":
        serve(args.output)
    elif args.command == "worker":
        worker(args.output, args.job)
    elif args.command == "status":
        status(args)
    else:
        if not (args.output / "campaign.json").exists():
            parser.error("No campaign exists here")
        atomic_text(args.output / "stop.request", utc()+"\n")
        print("Stop requested. Active workers will stop within the next controller poll.")


if __name__ == "__main__":
    main()
