# Construction catalogue

This directory holds the construction tools, the proposed puzzles, their
solutions, and shareable English cards. Every proposal has its own stable
directory. Future proposals can be added without overwriting earlier designs.

## Published proposals

| Proposal | Clues | Puzzle | Solution (spoiler) |
|---|---|---|---|
| 01 - Even Island | Four thermometers, 20 marked cells, no given digits | [PNG](even_island_01/puzzle.png), [SVG](even_island_01/puzzle.svg), [PDF](even_island_01/puzzle.pdf) | [PNG](even_island_01/solution.png), [SVG](even_island_01/solution.svg), [JSON](even_island_01/solution.json) |

![Even Island - standalone puzzle](even_island_01/puzzle.png)

The PNG is a complete statement: it includes the Sudoku rules, thermometer
rules, the side-connected-even-island rule, and the distinction between
diagonal line segments and side adjacency. It contains no solution digits or
parity marks. The solution is on a separately labeled card.

Each PNG is **2160 x 2580 pixels**, rendered at 3x scale directly from its SVG.
The PNG embeds the SHA-256 digest of that SVG. The renderer checks uniqueness
before building either card. The solution card highlights even cells so that
the island can be inspected directly.

The [machine-readable puzzle](even_island_01/puzzle.json) and
[recorded verification](even_island_01/verification.json) accompany proposal 01.
Its island rule, all four lines and all eight endpoints are essential under
the documented removal tests. This is local irreducibility, not a global
minimum clue count or a human difficulty rating. The [analysis](analysis.md)
explains the digit freedom, uniqueness checks, and construction method.

## Check and rebuild the cards

Run all commands from the repository root. Checking uses only the standard
library and leaves the artwork untouched:

```sh
python -m constructions.build --check
python island_puzzles.py verify constructions/even_island_01/puzzle.json --audit
```

The check reruns the exact verifier, compares the saved solution with its
unique completion, checks both SVG sources, and validates each PNG's size,
chunk integrity and source digest. It does not claim pixel-for-pixel rendering
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
an image by hand is unnecessary; edit the JSON or renderer and rebuild.

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
```

The default target is the first digit completion of the reference island.
`--target` accepts another valid connected-even Sudoku in the same solution
JSON format. Path lengths, line count, iterations and time are configurable.
The selection order is deterministic. Search outputs a new puzzle JSON only
on `FOUND` and refuses to overwrite existing output files.

`NO_COVER_IN_POOL` concerns only that target, finite candidate-path pool and
line budget. It does not rule out other targets, other line types, or all
three-line constructions. A time or iteration limit gives `UNKNOWN`. The
search currently constructs thermometers; the shared verifier also supports
whisper lines.

To publish a new candidate, create a new folder such as `even_island_02`, place
the accepted puzzle JSON there as `puzzle.json`, run the exact audit, and build
its cards. Add a row to this catalogue after inspecting both rendered PNGs.
The existing proposal remains unchanged by searches for future designs.

## Layout

```text
constructions/
  README.md                 Catalogue and reproduction instructions
  analysis.md               Mathematical freedom and design analysis
  search.py                 Bounded, exact-checked construction search
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
```
