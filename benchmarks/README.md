# Rule-only automatic solving benchmark

[Measured results and comparison table](report.md) · [Raw JSON](results.json) ·
[Per-trial CSV](results.csv)

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
