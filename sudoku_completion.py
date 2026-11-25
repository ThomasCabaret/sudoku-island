"""Complete an abstract 9x9 island with even digits, independently of its search."""

from __future__ import annotations

from collections.abc import Sequence


def validate_sudoku(grid: Sequence[Sequence[int]], rows: Sequence[int]) -> bool:
    """Independently check Sudoku rules and exact agreement with even cells."""
    if len(grid) != 9 or any(len(row) != 9 for row in grid):
        return False
    if len(rows) != 9 or any(type(mask) is not int or not 0 <= mask < 512 for mask in rows):
        return False
    if any(type(digit) is not int or not 1 <= digit <= 9 for row in grid for digit in row):
        return False
    digits = set(range(1, 10))
    if any(set(row) != digits for row in grid):
        return False
    if any({grid[r][c] for r in range(9)} != digits for c in range(9)):
        return False
    for br in range(0, 9, 3):
        for bc in range(0, 9, 3):
            if {grid[r][c] for r in range(br, br + 3) for c in range(bc, bc + 3)} != digits:
                return False
    return all((grid[r][c] % 2 == 0) == bool(rows[r] >> c & 1) for r in range(9) for c in range(9))


def complete_sudoku(rows: Sequence[int]) -> tuple[tuple[int, ...], ...] | None:
    """Return a Sudoku whose even cells are exactly the given island, if one exists.

    This is a separate exact backtracking search, with no extension assumption.
    None means this particular pattern has no completion, not that all abstract
    islands are uncompletable. The input must be an abstract k=4 island.
    """
    from sudoku_island import validate_pattern

    if not validate_pattern(rows, 4):
        raise ValueError("Completion requires a valid 9x9 island with k=4")
    even = sum(1 << (digit - 1) for digit in (2, 4, 6, 8))
    odd = 511 ^ even
    allowed = [even if rows[r] >> c & 1 else odd for r in range(9) for c in range(9)]
    units = [(r, c, r // 3 * 3 + c // 3) for r in range(9) for c in range(9)]
    row_used, column_used, box_used = [0] * 9, [0] * 9, [0] * 9
    values = [0] * 81

    def search() -> bool:
        best_cell, best_domain = -1, 0
        best_size = 10
        for cell, value in enumerate(values):
            if value:
                continue
            r, c, b = units[cell]
            domain = allowed[cell] & ~(row_used[r] | column_used[c] | box_used[b])
            size = domain.bit_count()
            if size == 0:
                return False
            if size < best_size:
                best_cell, best_domain, best_size = cell, domain, size
        if best_cell == -1:
            return True
        r, c, b = units[best_cell]
        while best_domain:
            bit = best_domain & -best_domain
            best_domain ^= bit
            values[best_cell] = bit.bit_length()
            row_used[r] |= bit
            column_used[c] |= bit
            box_used[b] |= bit
            if search():
                return True
            row_used[r] ^= bit
            column_used[c] ^= bit
            box_used[b] ^= bit
            values[best_cell] = 0
        return False

    if not search():
        return None
    grid = tuple(tuple(values[r * 9:r * 9 + 9]) for r in range(9))
    if not validate_sudoku(grid, rows):
        raise RuntimeError("Internal error: the independent Sudoku check failed")
    return grid


def format_sudoku(grid: Sequence[Sequence[int]]) -> str:
    border = "+-------+-------+-------+"
    lines = []
    for r, row in enumerate(grid):
        if r % 3 == 0:
            lines.append(border)
        lines.append("| " + " | ".join(" ".join(map(str, row[c:c + 3])) for c in range(0, 9, 3)) + " |")
    return "\n".join(lines + [border])
