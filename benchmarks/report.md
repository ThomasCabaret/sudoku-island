# Rule-only solver benchmark

These solvers receive only each published `puzzle.json`: Sudoku rules,
line clues, printed parity marks and orthogonal even-cell connectivity.
They do **not** receive the island theorem, eight orientations, a fixed
parity mask, the expected filling or construction/removal certificates.

Recorded at 2026-11-25T12:22:58.996227+00:00. 2 fresh-process runs per cell,
a 30 s wall-time budget per run, sequential execution, shuffled order
with seed 0. Values below are medians; raw trials include all counters.
The search first seeks one solution, then continues to prove uniqueness.
The uniqueness time includes the first-solution phase.

Environment: Windows-11-10.0.26200-SP0; Python 3.12.5;
13th Gen Intel(R) Core(TM) i7-13700H; 20 logical CPUs.
Z3: 5.0.0. Each worker uses one solver thread.

| Puzzle | Method | First solution (s) | Uniqueness | Search work | Peak MiB | CPU s |
|---|---|---:|---|---:|---:|---:|
| Even Island | `csp-leaf` | >30 (0/2) | UNKNOWN at 30 s | 97,605 nodes | 18.5 | 29.53 |
| Even Island | `csp-graph` | >30 (0/2) | UNKNOWN at 30 s | 59,464 nodes | 20.0 | 29.53 |
| Even Island | `sat-cuts` | >30 (0/2) | UNKNOWN at 30 s | 298,943 decisions | 72.7 | 29.66 |
| Two Anchors | `csp-leaf` | >30 (0/2) | UNKNOWN at 30 s | 83,624 nodes | 18.6 | 29.72 |
| Two Anchors | `csp-graph` | >30 (0/2) | UNKNOWN at 30 s | 76,081 nodes | 19.5 | 29.58 |
| Two Anchors | `sat-cuts` | 16.593 (2/2) | UNKNOWN at 30 s | 250,096 decisions | 69.7 | 29.52 |
| Whispered Island | `csp-leaf` | >30 (0/2) | UNKNOWN at 30 s | 80,048 nodes | 18.5 | 29.55 |
| Whispered Island | `csp-graph` | >30 (0/2) | UNKNOWN at 30 s | 60,070 nodes | 19.6 | 29.66 |
| Whispered Island | `sat-cuts` | >30 (0/2) | UNKNOWN at 30 s | 253,818 decisions | 69.3 | 29.57 |
| Two Even Anchors | `csp-leaf` | >30 (0/2) | UNKNOWN at 30 s | 81,060 nodes | 18.4 | 29.64 |
| Two Even Anchors | `csp-graph` | >30 (0/2) | UNKNOWN at 30 s | 63,720 nodes | 19.3 | 29.63 |
| Two Even Anchors | `sat-cuts` | >30 (0/2) | UNKNOWN at 30 s | 287,948 decisions | 71.2 | 29.51 |

## Reading the results

UNKNOWN means the search was interrupted, not that the puzzle has no
solution or that uniqueness failed. The existing exhaustive theorem-based
audits remain separate evidence; they are deliberately excluded here.

CSP nodes are calls to the recursive search, including branches that fail
during propagation. SAT decisions are internal Boolean choices. They are
**not comparable units**; compare work only within the same method.
More nodes in a timed-out run can simply mean cheaper nodes, rather than
a closer approach to a solution. Rejected disconnected grids are not puzzle
solutions. SAT statistics are the engine's cumulative counters at the final
incremental check; `sat_calls` counts those checks, including the last timeout.

Peak memory is the process high-water resident working set (MiB), including
the interpreter, imports and native Z3 allocations. It is not just search
data, nor a sampling-based estimate. Wall/CPU timings include model setup
and propagation-table construction, exclude process startup and JSON input
parsing, and include Z3 import/setup for SAT. Parent-observed process duration
is also saved in the raw results. Limits are cooperative, with a 10 s hard
kill grace; any overrun is reported in actual elapsed time.

This is a small local automatic-search benchmark, **not a human difficulty
rating**, a comparison of languages, or a claim about the best possible
Sudoku/constraint solvers. Two CSP configurations share an implementation;
the SAT encoding uses a different search engine. Repetitions share the same
deterministic search order and measure local timing variation, not seed variation.

See [methodology and commands](README.md), [raw results](results.json) and
[per-trial CSV](results.csv). Puzzle and solver-source SHA-256 hashes are
recorded in the JSON (source hashes normalize CRLF to LF).
