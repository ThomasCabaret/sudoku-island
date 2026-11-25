"""Rebuild or check standalone puzzle and solution cards from their JSON sources.

Run from the repository root: python -m constructions.build [--check].
PyMuPDF is needed only to render artwork: pip install -e ".[artwork]".
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
from typing import Sequence
import zlib

from island_puzzles import CARD_AUTHOR, CARD_HEIGHT, CARD_WIDTH, audit, load_parity, load_puzzle, render_svg, verify


CATALOG = Path(__file__).resolve().parent
SCALE = 3


def png_with_source(png: bytes, svg: bytes) -> bytes:
    """Embed the SVG digest in a standard PNG text chunk, before IEND."""
    payload = b"Source-SHA256\0" + sha256(svg).hexdigest().encode("ascii")
    kind = b"tEXt"
    chunk = struct.pack(">I", len(payload)) + kind + payload
    chunk += struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    if png[-12:] != b"\0\0\0\0IEND\xaeB`\x82":
        raise ValueError("Expected a complete PNG stream")
    return png[:-12] + chunk + png[-12:]


def check_png(path: Path, svg: bytes) -> None:
    """Detect missing, truncated, corrupt, wrong-size or stale-source PNG files."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Invalid PNG: {path}")
    offset, digest, size, ended = 8, None, None, False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError(f"Truncated PNG: {path}")
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if crc != zlib.crc32(kind + payload) & 0xFFFFFFFF:
            raise ValueError(f"Corrupt PNG chunk: {path}")
        if kind == b"IHDR":
            size = struct.unpack(">II", payload[:8])
        elif kind == b"tEXt" and payload.startswith(b"Source-SHA256\0"):
            digest = payload.split(b"\0", 1)[1].decode("ascii")
        elif kind == b"IEND":
            ended = end == len(data)
            break
        offset = end
    if not ended or size != (CARD_WIDTH * SCALE, CARD_HEIGHT * SCALE) or digest != sha256(svg).hexdigest():
        raise ValueError(f"Missing, stale or wrong-size PNG card: {path}")


def _render_files(svg_path: Path) -> None:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('Install the artwork extra: python -m pip install -e ".[artwork]"') from exc
    svg_bytes = svg_path.read_bytes()
    with fitz.open(stream=svg_bytes, filetype="svg") as source:
        with fitz.open(stream=source.convert_to_pdf(), filetype="pdf") as vector:
            png = vector[0].get_pixmap(matrix=fitz.Matrix(SCALE, SCALE)).tobytes("png")
            svg_path.with_suffix(".png").write_bytes(png_with_source(png, svg_bytes))
            if svg_path.stem == "puzzle":
                with fitz.open() as pdf:
                    page = pdf.new_page(width=841.89, height=595.276)
                    page.show_pdf_page(fitz.Rect(18, 18, 823.89, 577.276), vector, 0)
                    pdf.set_metadata({"title": svg_path.parent.name + " - puzzle", "author": CARD_AUTHOR})
                    pdf.save(svg_path.with_suffix(".pdf"), garbage=4, deflate=True)


def _compact(value):
    if isinstance(value, dict):
        return {key: ["".join(str(d) for row in grid for d in row) for grid in item]
                if key == "solutions" else _compact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_compact(item) for item in value]
    return value


def design_metrics(lines, parity) -> dict:
    turns = 0
    for line in lines:
        directions = [(b // 9 - a // 9, b % 9 - a % 9) for a, b in zip(line.cells, line.cells[1:])]
        turns += sum(a != b for a, b in zip(directions, directions[1:]))
    cells = {cell for line in lines for cell in line.cells}
    return {
        "line_count": len(lines), "parity_mark_count": len(parity),
        "clue_count": len(lines) + len(parity),
        "line_cells": len(cells), "marked_cells": len(cells | {m.cell for m in parity}),
        "segments": sum(len(line.cells) - 1 for line in lines), "turns": turns,
        "longest_line": max((len(line.cells) for line in lines), default=0),
        "clue_families": sorted({line.kind for line in lines} | ({"parity"} if parity else set())),
    }


def build(proposal: Path, *, check: bool = False) -> None:
    """Require an exact unique solution before writing any cards."""
    data, lines = load_puzzle(proposal / "puzzle.json")
    # Canonical JSON keeps this digest stable across Git's LF/CRLF conversion.
    puzzle_digest = sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    parity = load_parity(data)
    result = verify(lines, parity=parity)
    if result.status != "UNIQUE":
        raise ValueError(f"{proposal.name} is {result.status}; refusing to publish a unique-solution card")
    grid = result.solutions[0]
    solution = {"schema_version": 1, "puzzle": "puzzle.json", "status": "UNIQUE", "grid": grid}
    solution_bytes = (json.dumps(solution, indent=2) + "\n").encode("utf-8")
    sources = {
        "puzzle.svg": render_svg(lines, data.get("title", "Even Island"), parity=parity, verified_unique=True),
        "solution.svg": render_svg(lines, data.get("title", "Even Island"), solution=grid, parity=parity, verified_unique=True),
    }
    if check:
        report = json.loads((proposal / "verification.json").read_text(encoding="utf-8"))
        if report.get("puzzle_sha256") != puzzle_digest:
            raise ValueError(f"Stale verification record: {proposal}")
        recorded = json.loads((proposal / "solution.json").read_text(encoding="utf-8"))
        if recorded != json.loads(solution_bytes):
            raise ValueError(f"Stale solution: {proposal}")
        for name, svg in sources.items():
            expected = svg.encode("utf-8")
            if (proposal / name).read_bytes() != expected:
                raise ValueError(f"Stale SVG: {proposal / name}")
            check_png((proposal / name).with_suffix(".png"), expected)
    else:
        (proposal / "solution.json").write_bytes(solution_bytes)
        for name, svg in sources.items():
            path = proposal / name
            path.write_bytes(svg.encode("utf-8"))
            _render_files(path)
        report_path = proposal / "verification.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        legacy_digest = sha256((proposal / "puzzle.json").read_bytes()).hexdigest()
        if report.get("puzzle_sha256") not in (puzzle_digest, legacy_digest):
            report = {"freedom": report["freedom"]} if "freedom" in report else {}
        report.update({
            "schema_version": 1, "puzzle": "puzzle.json", "puzzle_sha256": puzzle_digest,
            "grid_encoding": "Each solution is an 81-character row-major digit string.",
            "design_metrics": design_metrics(lines, parity),
            "audit": _compact(audit(lines, parity=parity)),
            "qualification": "Removal/endpoint irreducibility is local. No global minimum clue count or human difficulty rating is claimed.",
        })
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{proposal.name}: UNIQUE; {'checked' if check else 'built'} English puzzle and solution cards")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", nargs="?", type=Path, help="proposal directory; default: all catalogue entries")
    parser.add_argument("--check", action="store_true", help="validate sources, solutions and PNG provenance without rendering")
    args = parser.parse_args(argv)
    try:
        proposals = [args.proposal] if args.proposal else sorted(path.parent for path in CATALOG.glob("*/puzzle.json"))
        if not proposals:
            raise ValueError("No proposal directories were found")
        for proposal in proposals:
            build(proposal, check=args.check)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
