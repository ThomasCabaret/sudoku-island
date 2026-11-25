# Rule-only solver benchmark

These are ordinary classic Sudokus with printed numeric givens.
No even-island rule, parity pattern or variant clue is imposed.
CSP and SAT use the same search engines as the island benchmarks,
with only the applicable statement constraints enabled.

Recorded at 2026-11-25T17:41:56.670697+00:00. 5 fresh-process runs per cell,
a 1800 s initial wall-time budget per run, sequential execution, shuffled order
with seed 0. Values below are medians; raw trials include all counters.
The search first seeks one solution, then continues to prove uniqueness.
Uniqueness gets a separate 1800 s budget; the table reports its additional time after the first solution.

Environment: Windows-11-10.0.26200-SP0; Python 3.12.5;
13th Gen Intel(R) Core(TM) i7-13700H; 20 logical CPUs.
Z3: 5.0.0. Each worker uses one solver thread.

| Puzzle | Method | First solution (s) | Additional uniqueness | Search work | Peak MiB | CPU s |
|---|---|---:|---|---:|---:|---:|
| AI Escargot | `csp-leaf` | 0.004 (5/5) | 0.026 s (5/5) | 143 nodes | 18.4 | 0.03 |
| AI Escargot | `sat-cuts` | 0.100 (5/5) | 0.002 s (5/5) | 131 decisions | 45.4 | 0.08 |
| Golden Nugget | `csp-leaf` | 0.095 (5/5) | 0.022 s (5/5) | 470 nodes | 18.4 | 0.12 |
| Golden Nugget | `sat-cuts` | 0.100 (5/5) | 0.002 s (5/5) | 146 decisions | 45.5 | 0.09 |
| Platinum Blonde | `csp-leaf` | 0.010 (5/5) | 0.194 s (5/5) | 844 nodes | 18.4 | 0.20 |
| Platinum Blonde | `sat-cuts` | 0.099 (5/5) | 0.003 s (5/5) | 256 decisions | 45.4 | 0.09 |
| Everest (Inkala) | `csp-leaf` | 0.043 (5/5) | 0.035 s (5/5) | 321 nodes | 18.4 | 0.08 |
| Everest (Inkala) | `sat-cuts` | 0.097 (5/5) | 0.003 s (5/5) | 212 decisions | 45.4 | 0.09 |

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
