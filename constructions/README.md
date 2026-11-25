# Construction catalogue

This directory holds the construction tools, the proposed puzzles, their
solutions, and shareable English cards. Every proposal has its own stable
directory. Future proposals can be added without overwriting earlier designs.

## Published proposals

| Proposal | Clues | Puzzle | Solution (spoiler) |
|---|---|---|---|
| 01 - Even Island | Four thermometers, 19 marked cells | [PNG](even_island_01/puzzle.png), [SVG](even_island_01/puzzle.svg), [PDF](even_island_01/puzzle.pdf) | [PNG](even_island_01/solution.png), [SVG](even_island_01/solution.svg), [JSON](even_island_01/solution.json) |
| 02 - Two Anchors | Two parity marks, four short thermometers, 20 marked cells | [PNG](even_island_02/puzzle.png), [SVG](even_island_02/puzzle.svg), [PDF](even_island_02/puzzle.pdf) | [PNG](even_island_02/solution.png), [SVG](even_island_02/solution.svg), [JSON](even_island_02/solution.json) |
| 03 - Whispered Island | Two German whispers and one two-cell thermometer, 24 marked cells | [PNG](even_island_03/puzzle.png), [SVG](even_island_03/puzzle.svg), [PDF](even_island_03/puzzle.pdf) | [PNG](even_island_03/solution.png), [SVG](even_island_03/solution.svg), [JSON](even_island_03/solution.json) |
| 04 - Two Even Anchors | Two even squares, four four-cell thermometers, 18 marked cells | [PNG](even_island_04/puzzle.png), [SVG](even_island_04/puzzle.svg), [PDF](even_island_04/puzzle.pdf) | [PNG](even_island_04/solution.png), [SVG](even_island_04/solution.svg), [JSON](even_island_04/solution.json) |

![Even Island - standalone puzzle](even_island_01/puzzle.png)

The PNG is a complete statement: it includes the Sudoku rules, thermometer
rules, the "orthogonally connected" even-island rule, and the distinction between
diagonal line segments and side adjacency. All proposals have no given
digits. Proposals 02 and 04 include two blue parity marks. Each solution
is on a separately labeled card.

Each PNG is **3840 x 2400 pixels**, rendered at 3x scale directly from its SVG.
The grid is on the left and the title and complete rules on the right.
The PNG embeds the SHA-256 digest of that SVG. The renderer checks uniqueness
before building either card. The solution card highlights even cells so that
the island can be inspected directly.

The [machine-readable puzzle](even_island_01/puzzle.json) and
[recorded verification](even_island_01/verification.json) accompany proposal 01.
Every published island rule, line, parity mark and removable endpoint is
essential under the recorded removal tests. All legal single-cell interior
thermometer shortcuts have also been tested and fail to preserve uniqueness.
This is local irreducibility, not a global
minimum clue count or a human difficulty rating. The [analysis](analysis.md)
explains the digit freedom, uniqueness checks, and construction method.

The separate [automatic-solving benchmark](../benchmarks/report.md) starts
from the printed statements and deliberately excludes the eight-mask theorem.
It reports bounded search effort and memory for three solver configurations.
See its [methodology and rerun commands](../benchmarks/README.md).

## What makes a useful elegant construction?

We compare several costs instead of treating every long line as one cheap
clue. A nine-cell thermometer can encode nine fixed digits, so minimizing
line count alone can make a puzzle less interesting.

| Proposal | Lines | Parity marks | Marked cells | Segments | Turns | Rule families beyond Sudoku and connectivity |
|---|---:|---:|---:|---:|---:|---|
| 01 | 4 | 0 | 19 | 15 | 11 | Thermometers |
| 02 | 4 | 2 | 20 | 14 | 9 | Parity, thermometers |
| 03 | 3 | 0 | 24 | 21 | 14 | Thermometers, German whispers |
| 04 | 4 | 2 | 18 | 12 | 5 | Even squares, thermometers |

These alternatives trade different costs. Proposal 01 uses one familiar clue
family and the least marked area. Proposal 02 makes the geometry-vs-digits
separation explicit with short thermometers. Proposal 03 uses fewer lines and
has a clear final symmetry-breaking clue, at the cost of longer paths and
another rule family. Counts of turns are descriptive, not a human difficulty
score. All artwork avoids line crossings, shared line cells, and parity marks
on the lines.

Our acceptance criteria are: exact uniqueness over all eight island masks;
an essential connectivity rule; essential individual clues; irreducibility
under line removal, endpoint trimming, and legal thermometer shortcuts;
readable geometry; and no printed digit values. A satisfying manual solve
path still requires human testing. In particular, exact uniqueness is not
evidence that discovering the island theorem is easy for a solver.

### Two Anchors: a genuinely global parity variant

The blue square at r1c1 is even and the blue circle at r8c9 is odd. Before
adding lines, these two marks select the reference orientation from all eight.
Neither singleton can do so. Exhaustive checks of all 81 singleton positions
and all 3,240 pairs find **378 orienting pairs** for the reference mask.
By square symmetry the singleton impossibility covers all orientations.
Thus **two is the exact minimum for orientation alone**. See
[parity-analysis.json](parity-analysis.json) and `parity.py`.

The two marks alone still leave 39,820,492,800 digit fillings; they do not
specify any numeric value. Their role survives in the completed puzzle:

| Constraints on proposal 02 | Exact filled-grid count |
|---|---:|
| Four thermometers, no parity marks | 743 |
| Thermometers and the even square only | 397 |
| Thermometers and the odd circle only | 246 |
| Thermometers and both marks | 1 |

Every number in this table comes from finished enumeration across all eight
masks. The marks lie off the thermometers, and removing either mark allows a
different island orientation. This separates a global geometry clue from a
local given digit. The four thermometers then determine the digit filling.
Two is not claimed to be a minimum number of total clues.

### Whispered Island: one inequality breaks the complement

The two green lines leave **exactly two** filled grids, related by `d -> 10-d`.
The two-cell thermometer eliminates one. Zero directional clues cannot
distinguish that pair; one suffices for these fixed whispers. This is a
conditional minimum, not a proof that all possible two-line puzzles fail.
German whisper neighbors differ by at least 5; no negative constraint applies
off the lines. No givens or parity marks appear in this proposal.

### Two Even Anchors: all parities fixed before digit construction

Proposal 04 marks **r1c4 and r9c9 as even**. Those two squares alone fix the
entire parity geometry, with no odd mark. Digit construction then works with
all 81 parities already determined. The final verifier independently checks
all eight masks using only the actual printed clues and the connectivity rule.

The verified result uses **four thermometers of four cells**, no overlaps or
crossings, and 18 marked cells including the two squares. Every mark, line and
endpoint is essential; legal interior thermometer shortcuts are also excluded.
The island rule remains essential. This improves marked area and path length
over proposal 02, but **does not meet the requested three-thermometer cap**.

For this particular completed grid, **four is the minimum number of standard
noncrossing king-adjacent thermometers of at most four cells**. The
[short-bound certificate](even_island_04/short-bound.json) proves that three
cannot isolate this filling even when all parities are supplied and different
thermometers may share cells or cross each other. A thermometer itself is a
simple, noncrossing path. This is a fixed-filling lower bound, not a proof
that a different Sudoku filling cannot achieve three.

The certificate contains 30 independently valid alternative Sudokus sharing
the full parity pattern. Twenty-four of them are not global digit relabelings.
For every possible increasing path of two, three or four cells in the target,
we record which alternatives it rejects. No choice of three paths rejects
them all. This necessary hitting-set condition already rules out uniqueness.
The certificate checker reconstructs every path, checks every witness with
the whole-grid validator, and uses the separate generic exact cover search.
It does not trust a timeout or a search log as an impossibility certificate.

Exploration also rejected all 2,880 parity-preserving digit relabelings of
each of the proposal 01 and proposal 02 fillings, plus 300 varied sampled
completions, under the three-by-four profile. See [research.json](even_island_04/research.json).
These are selected structural filling classes, not the whole 318-billion-grid
space. The global existence of a three-by-four construction remains open.

```sh
python -m constructions.short_thermos --check-certificate constructions/even_island_04/short-bound.json
python -m constructions.short_thermos --target constructions/even_island_04/solution.json --max-lines 3 --max-length 4 --allow-overlap --certificate output/short-bound.json --output output/strict.json
python -m constructions.short_thermos --target constructions/even_island_04/solution.json --max-lines 4 --max-length 4 --seconds-per-target 90 --allow-overlap --output output/four-short.json
python -m constructions.short_thermos --max-lines 3 --max-length 4 --targets 300 --seed 400 --allow-overlap --output output/short-candidate.json
python -m constructions.short_thermos --relabel-from constructions/even_island_04/solution.json --targets 2880 --allow-overlap --output output/relabel-candidate.json
```

The tool seeds its counterexamples with valid bichromatic-component (Kempe)
swaps, eliminating many impossible target/clue combinations before querying
the full Sudoku solver. Random completions vary variable order as well as
digit labels; they are reproducible samples, not claimed uniform samples.
`NO_COVER_IN_POOL` is local to its target and path bounds; `UNKNOWN` means a
budget ran out. Negative outcomes are never published as unique puzzles.

## Check and rebuild the cards

Run all commands from the repository root. Checking uses only the standard
library and leaves the artwork untouched:

```sh
python -m constructions.build --check
python island_puzzles.py verify constructions/even_island_01/puzzle.json --audit
```

The check reruns the exact verifier, compares the saved solution with its
unique completion, checks both SVG sources, and validates each PNG's size,
chunk integrity and source digest, and the verification record's canonical
JSON source digest. It does not claim pixel-for-pixel rendering
identity across different renderer versions.

To regenerate all cards and the printable puzzle PDF:

```sh
python -m pip install -e ".[artwork]"
python -m constructions.build
```

Only artwork generation needs the optional PyMuPDF dependency. Solving and
construction search remain standard-library-only. To rebuild one proposal:

```sh
python -m constructions.build constructions/even_island_01
```

The blank card and solution card are generated from the same puzzle JSON.
The grid in `solution.json` is recomputed and independently validated. Editing
an image by hand is unnecessary; edit the JSON or renderer and rebuild. The
build also refreshes the compact verification audit and design metrics.

## Search for another construction

`search.py` preserves the counterexample-guided construction method. It
generates increasing, noncrossing king-adjacent paths on a target Sudoku,
solves a bounded hitting-set problem against competing grids, checks all
eight island orientations, and trims redundant clues and endpoints.
It accepts a result only if the island rule is also essential.

```sh
python -m constructions.search --output output/candidate.json
python -m constructions.search --max-lines 3 --timeout 120 --output output/three-line-candidate.json
python -m constructions.search --target constructions/even_island_01/solution.json --output output/another-candidate.json
python -m constructions.search --target constructions/even_island_02/solution.json --parity-from constructions/even_island_02/puzzle.json --min-length 3 --max-lines 4 --max-iterations 400 --output output/parity-candidate.json
python -m constructions.search --target constructions/even_island_03/solution.json --profile mixed --max-lines 3 --output output/whisper-candidate.json
python -m constructions.parity --json output/parity-analysis.json
```

The default target is the first digit completion of the reference island.
`--target` accepts another valid connected-even Sudoku in the same solution
JSON format. Path lengths, line count, iterations and time are configurable.
`--profile mixed` adds a bounded, reproducible sample of German whisper paths;
`--profile renban` offers an experimental renban/thermometer search. Renban
digits are consecutive and nonrepeating in any order. No renban proposal is
published here yet. `--seed` controls sampled paths. The mixed-profile time
budget applies after preparing the path pool.

The selection order is deterministic. Search outputs a new puzzle JSON only
on `FOUND` and refuses to overwrite existing output files.

`NO_COVER_IN_POOL` concerns only that target, finite candidate-path pool and
line budget. It does not rule out other targets, other line types, or all
three-line constructions. A time or iteration limit gives `UNKNOWN`. When
parity marks are supplied, redundant-mark designs are rejected; exhaustion
after those heuristic rejections is also UNKNOWN, not an impossibility
certificate. The verifier supports parity marks, thermometers, German whispers
and renban lines; proposed cards must spell out every applicable rule.

To publish a new candidate, create a new folder such as `even_island_02`, place
the accepted puzzle JSON there as `puzzle.json`, run the exact audit, and build
its cards. Add a row to this catalogue after inspecting both rendered PNGs.
The existing proposal remains unchanged by searches for future designs.

## Layout

```text
constructions/
  README.md                 Catalogue and reproduction instructions
  analysis.md               Mathematical freedom and design analysis
  search.py                 Bounded thermometer/whisper/renban construction search
  parity.py                 Exhaustive minimum-orientation-mark analysis
  parity-analysis.json      Recorded two-mark minimum and example
  short_thermos.py           Fixed-geometry construction and lower-bound checker
  build.py                  SVG, PNG, PDF and solution generation/checking
  even_island_01/
    puzzle.json             Complete machine-readable statement
    puzzle.svg              Vector source of the blank card
    puzzle.png              Standalone English puzzle card
    puzzle.pdf              Printable A4 puzzle
    solution.json           Verified unique digit grid
    solution.svg            Vector source of the solution card
    solution.png            English solution card with even-cell shading
    verification.json       Recorded counts, witnesses and removal audits
  even_island_02/            Same files for Two Anchors
  even_island_03/            Same files for Whispered Island
  even_island_04/            Same files, plus short-bound.json and research.json
```
