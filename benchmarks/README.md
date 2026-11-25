# Rule-only automatic solving benchmark

[Measured results and comparison table](report.md) · [Raw JSON](results.json) ·
[Per-trial CSV](results.csv)

For longer unattended searches, see the [offline SAT campaign](#offline-sat-campaign).
The 30-second report is a historical measurement; it is not overwritten by a
campaign or silently updated to measurements from a newer solver version.

The purpose is to measure automatic solving effort when the **printed statement
is the only mathematical input**. The fast construction verifier is unsuitable
for this question: it imports the independently proved eight island masks.
None of the benchmark methods does that.

## Methods

Three configurations, two search families:

- **`csp-leaf`**: ordinary finite-domain depth-first backtracking. Naked singles,
  hidden singles in each Sudoku unit, binary arc consistency on thermometers
  and whispers, minimum remaining values (MRV), ascending digit order. It checks
  orthogonal even connectivity only at completed Sudoku grids; disconnected
  completions are rejected and search continues.
- **`csp-graph`**: the same search and ordering, with generic connectivity
  propagation. Each unit must have four even cells, since its digits are 1–9.
  The possible-even graph must have a component big enough to hold all 36 even
  cells, all mandatory-even cells, and at least four cells of every unit.
  Other components lose their even candidates. Articulation cells separating
  mandatory-even cells become even. This derives only necessary conditions
  from the rules; it does not preload any island pattern.
- **`sat-cuts`**: Z3's finite-domain SAT backend, Boolean cell/digit variables,
  exact-one constraints for cells and Sudoku units, and forbidden digit pairs
  for the printed lines. A full model with disconnected even cells produces
  sound connectivity cuts and search resumes incrementally, retaining learnt
  clauses. For each even component C, the cut is
  `(some cell of C becomes odd) OR (some orthogonal boundary cell becomes even)`.
  Because a disconnected C has fewer than 36 cells, every connected 36-cell
  island must satisfy this cut. No reference shape or orientation is needed.

The implementations also support renban lines, although the four published
puzzles currently contain none. Their support filtering/encoding requires a
nonrepeating consecutive digit set. These are general automatic constraint
methods, not simulations of named human Sudoku techniques.

## Information boundary and correctness

The worker [`solve.py`](solve.py) opens **only `puzzle.json`**. It receives no
expected filling, full parity pattern, symmetry orbit, symmetry breaking from
the theorem, removal audit, or lower-bound certificate. It does not call
`verify`, `symmetry_orbit`, `check_uniqueness`, or the abstract island search.
Some parsing, ordinary domain propagation and the independent whole-grid
validator are shared with the project; importing those helpers does not use
their theorem-dependent verifier. Tests poison those theorem entry points.

Both search families are complete without a time limit: domain branching enumerates all
digit assignments, and SAT blocks each accepted grid or rules out disconnected
components with valid cuts. UNIQUE requires exhausting the remaining space
after exactly one accepted grid. Two different accepted grids prove MULTIPLE.
Every accepted grid is checked independently against Sudoku units, line clues,
printed parity marks and an actual orthogonal flood fill. A timeout is UNKNOWN,
even if a first witness has been found. Nothing is inferred from the published
solution. The separate, much faster theorem-based uniqueness audits remain valid.

The graph propagation is sound: a final connected even set must lie in a single
possible-even component and contain each already required even cell. Its size
is 36 and its intersection with every Sudoku unit has size four. A vertex whose
removal separates required even cells must belong to that final set. These
tests can miss contradictions but cannot discard a valid completion.

## Reproduce

The CSP methods need only Python 3.10+. SAT uses the optional `benchmark` extra;
the main application still has no runtime dependencies. The exact Z3 version
used for the recorded run is saved in `results.json`.

```sh
python -m pip install '.[benchmark]'
python -m benchmarks.run --seconds 30 --repeats 2
```

This runs all four statements and three methods, **sequentially**, in fresh
processes, twice each, with a shuffled but reproducible order. It takes up to
about 12 minutes if all trials exhaust their budget. It writes the report,
JSON and CSV here. To avoid replacing the published measurements:

```sh
python -m benchmarks.run --seconds 60 --repeats 2 --output output/benchmark
python -m benchmarks.run --methods csp-leaf csp-graph --seconds 5 --repeats 1 --output output/csp-only
python -m benchmarks.solve constructions/even_island_04/puzzle.json --method sat-cuts --seconds 30 --output output/one-trial.json
```

Create `output/` before the last command if it does not exist. No benchmark runs
as part of the regular tests; CI checks small correctness fixtures instead.
Optional Z3 correctness tests are skipped when the extra is absent.

First-solution time and total uniqueness time come from the same continuing
search. The budget covers both, not a fresh allowance for each phase. Search
node counts and SAT decision counts are different metrics. Memory is a process
peak resident working set, not just Python allocations. See the measured report
for timing boundaries and interpretation of censored results.

The raw `engine_statistics` field is an unmodified Z3 snapshot. Decision and
conflict counters accumulate across incremental calls; `time` describes the
last check, and memory fields describe engine allocations. Use the worker's
`elapsed_seconds`, `cpu_seconds` and `peak_process_mib` for total time and
whole-process peak memory.

## Offline SAT campaign

From the repository root, double-click **`start_campaign.bat`** to launch a
detached controller. **`campaign_status.bat`** opens an automatically refreshing
table; closing that viewer leaves the calculation running. **`stop_campaign.bat`**
requests cancellation of this campaign's workers. No unrelated Python process
is terminated.

Defaults: four published puzzles, two SAT models, two simultaneous workers,
one solver thread each. Every job gets **30 minutes to find its first solution**,
then a **new 30-minute budget** for excluding a second solution. Solved jobs
finish early. With eight jobs and two workers, the worst-case allowance is
about four hours, plus setup. CPU contention means these are campaign timings,
not directly comparable to the sequential 30-second benchmark.

The two recorded times are:

- `first_solution_seconds`: setup and search until the first validated grid;
- `uniqueness_search_seconds`: additional time after that grid, continuing the
  same solver with its learnt clauses and blocking the entire digit assignment.
  It is a completed uniqueness proof only if the final status is **UNIQUE**.
  MULTIPLE means a second different grid was found; UNKNOWN means interruption.

The original `sat-cuts` model learns clauses from disconnected complete models.
The new **`sat-tree`** model instead includes connectivity in the initial SAT
formula. Each selected cell has an unsigned six-bit rank at most 35. The root
has rank zero; every other selected cell has an orthogonally adjacent selected
neighbor of strictly smaller rank. The root is the first even cell in row one,
which necessarily contains four evens. This chooses auxiliary variables without
restricting the grid's geometric orientation. In either model, only the
printed clues are input; no reference mask or expected solution is provided.

Why the tree encoding is exact: descending ranks force every even cell to
reach the same root, so the selected set is connected. Conversely, in any
connected 36-cell set, shortest-path distances from that root are at most 35
and satisfy all these constraints. Cycles in the island are allowed. Blocking
a solution blocks its **81 digits**, not just one assignment of auxiliary ranks.
Tests compare the encoding with flood fill for all 512 selections on a 3x3 grid,
then check full Sudoku fixtures with the theorem entry points disabled.

Progress is saved under **`output/sat-campaign/`**:

- `status.md` and `summary.csv`: live comparison table, refreshed every two seconds;
- `campaign.json`: controller heartbeat, worker PIDs, settings and input/source hashes;
- per-job `*.progress.json`, `*.result.json`, and `*.log`: witnesses, phase times,
  final statuses, search counters and diagnostics;
- `snapshot/`: frozen solver source and the four statements, with no solution
  files or theorem-result files. Queued jobs use this snapshot even if the
  working repository changes during the campaign.

The controller runs independently of the launching terminal and prevents
automatic Windows sleep while it is active, without keeping the display on or
changing persistent power settings. Explicit sleep, shutdown or reboot still
interrupt computation. Saved progress is an audit snapshot, **not a checkpoint
of Z3's learnt clauses**. Starting again resumes the queue and retains completed
jobs, but interrupted jobs restart from scratch. Existing directories retain
their original settings and frozen source; use another directory for a new run.

Native SAT calls can last many minutes. Elapsed times keep advancing in the
viewer while counters and memory show the latest saved snapshot. This is not
a percentage-complete estimate. Once all jobs finish, the state becomes
FINISHED (or FINISHED_WITH_ERRORS if a worker failed). These searches do not
export independently checkable UNSAT proof certificates; UNIQUE is the SAT
engine's exhaustive UNSAT result after blocking the first independently
validated digit grid, under the documented exact encoding.

```sh
python -m benchmarks.campaign start
python -m benchmarks.campaign status
python -m benchmarks.campaign status --watch
python -m benchmarks.campaign stop
# New run with longer budgets, leaving the original run untouched:
python -m benchmarks.campaign start --solution-seconds 3600 --proof-seconds 3600 --output output/sat-campaign-longer
```
