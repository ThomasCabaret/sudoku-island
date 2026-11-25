# Famous classic Sudokus compared with Even Island

Recorded on **25 November 2026**, using the same local CSP and Z3 SAT search
engines as the island benchmark. These reference puzzles use **ordinary Sudoku
rules and their printed numeric givens only**. No connected-even rule is added.

## Exact inputs and sources

| Reference | Givens | Machine-readable input | Source |
|---|---:|---|---|
| AI Escargot | 23 | [JSON](ai_escargot.json) | [SudokuWiki corrected definition and loader](https://www.sudokuwiki.org/Escargot) |
| Golden Nugget | 21 | [JSON](golden_nugget.json) | [Tjark Weber's Isabelle Sudoku theory, explicitly labeled Golden Nugget](https://isabelle.in.tum.de/library/HOL/HOL-ex/Sudoku.html) |
| Platinum Blonde | 21 | [JSON](platinum_blonde.json) | [David Bernier's 2013 sci.math posting, attributed to coloin](https://groups.google.com/g/sci.math/c/HXZfuNub7Cs) |
| Everest (Inkala) | 21 | [JSON](everest.json) | [Andrew Stuart's Inkala article and linked puzzle](https://www.sudokuwiki.org/Arto_Inkala_Sudoku) |

AI Escargot uses the corrected 23-clue version, with **no given 1 at r8c3**.
Golden Nugget follows the Isabelle coordinates; the [Sudoku Snake presentation](https://www.sudokusnake.com/goldennugget.php)
swaps columns 5 and 6. No row/column permutations or digit relabeling are applied
to the recorded inputs. Platinum Blonde also appears in the research paper
[The Chaos Within Sudoku](https://www.nature.com/articles/srep00725).
Names identify the selected grids; the report does not establish a universal
ranking of famous puzzles or their historical publication dates.

## Measured classic results

**All 40 trials returned UNIQUE**: four puzzles, two methods, five fresh-process
repetitions. Both methods always found the same filling for each puzzle. Each
reported column is its own median. All times in this table are **milliseconds**.
The second phase continues the first search; it is additional time, not total time.

| Reference | CSP first solution | CSP extra uniqueness | SAT first solution | SAT extra uniqueness |
|---|---:|---:|---:|---:|
| AI Escargot | 4.2 | 25.7 | 100.3 | 2.1 |
| Golden Nugget | 95.0 | 22.1 | 99.6 | 2.5 |
| Platinum Blonde | 9.9 | 193.8 | 99.4 | 2.9 |
| Everest (Inkala) | 42.8 | 35.1 | 97.4 | 3.2 |

The CSP uses naked/hidden singles, MRV and ascending-digit backtracking. The SAT
uses the same Boolean cell/digit exact-one encoding and Z3 QF_FD backend as the
island solver, with given-digit unit clauses. Without an island rule, the graph
CSP variant coincides with ordinary CSP, and the two SAT connectivity variants
coincide with plain SAT, so duplicate configurations are not timed separately.

Timing includes model setup (including Z3 import for SAT), but excludes Python
process startup and JSON input parsing. The roughly 0.1 s SAT totals include
that setup and should not be interpreted as a fine difficulty scale between
these classic grids. Completed total times, CPU, peak process memory, nodes and
SAT decisions are in the [full report](report.md), [raw JSON](results.json), and
[per-trial CSV](results.csv). A 1,800 s budget was available for each phase;
every trial finished without reaching it. Execution was sequential, with one
solver thread, seed 0 and deterministic shuffled trial order.

## Completed island campaign

These are the original rule-only offline results, **not** the fast verifier
that preloads the eight island masks. Both SAT encodings proved uniqueness for
all four statements. The campaign source was frozen at commit
`3528ae7b253768b53cdc0d25efbf9dca6601d748`; its source/input hashes and all eight
raw results are archived in [island-campaign.json](island-campaign.json).
Every witness was checked again against the printed rules when archiving, and
the two encodings returned the same digit grid for each statement.

Times below are **seconds**, with one trial per encoding/puzzle.

| Island | Cuts first solution | Cuts extra uniqueness | Cuts total | Tree total |
|---|---:|---:|---:|---:|
| Even Island | 257.7 | 196.6 | 454.3 | 1048.0 |
| Two Anchors | 11.3 | 64.9 | 76.2 | 292.5 |
| Whispered Island | 74.9 | 37.8 | 112.7 | 168.8 |
| Two Even Anchors | 184.9 | 63.3 | 248.2 | 1240.7 |

For these implementations and encodings, the island statements require much
more automatic-search effort than these famous classic examples. Their SAT-cut
totals are about **76 to 454 s**, versus about **0.1 s** for the classic grids.
The earlier CSP island trials also all exhausted their 30 s budgets without a
first solution; the classic CSP proofs finish in about 0.03 to 0.20 s.

This is an **order-of-magnitude comparison**, not an exact speed ratio. The
classic runs are sequential five-run medians using the current input adapter;
the archived island campaign used two simultaneous workers, one run per job,
and an earlier frozen solver revision. Hardware, versions and per-run counters
are recorded. The results characterize these search methods and constraint
formulations; human solving difficulty has not been measured. In particular,
no claim is made that the islands are harder for people than AI Escargot.

## Reproduce from the repository root

```sh
python -m pip install '.[benchmark]'
python -m benchmarks.run --puzzles benchmarks/classics/ai_escargot.json benchmarks/classics/golden_nugget.json benchmarks/classics/platinum_blonde.json benchmarks/classics/everest.json --methods csp-leaf sat-cuts --seconds 1800 --proof-seconds 1800 --repeats 5 --output output/classic-comparison
```

The benchmark adapter accepts only an explicitly marked classic variant with
an 81-digit givens string (zero for blanks), no lines and no parity marks.
The zero-given island construction format is unchanged. Every returned grid
is independently checked for all Sudoku units and all printed givens. UNIQUE
requires exhaustive search after the first grid; no known solution is supplied
as input and no reference solution is used to prune search.
