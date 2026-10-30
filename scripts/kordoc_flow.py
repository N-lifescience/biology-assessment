"""Turn kordoc block trees into one flat, line-oriented document flow.

kordoc keeps every table as a full cell grid (covered cells are blank
placeholders behind the span anchor) and keeps nested structure inside cells.
School plans use that nesting heavily: a whole subject plan typed inside one
1×1 frame, a "평가방법 및 채점기준" label cell beside a cell that holds the real
rubric table, section titles drawn as one-row boxes ("Ⅲ │ │ 수행 평가 세부 계획").
A text parser cannot see headings or item boundaries inside such frames, so this
module flattens the tree before anything else reads it:

* frame tables (a cell holds a nested table and the frame is layout, not data)
  are unwrapped into their cells' blocks in reading order;
* one-row title boxes and short 1×1 boxes become headings, long 1×1 boxes become
  paragraphs;
* a small nested table that is part of a data table (the 평가 방법 checkbox grid
  inside one cell) is written into that cell as text rows, so every data table
  that leaves this module is a plain grid with no table inside it;
* "□V" / "□√" (a box overlaid with a check mark in HWP and PDF) becomes "☑".

``flow_text`` renders the flow as the restricted Markdown + HTML-table text the
detail parser reads: ``#`` headings, plain lines, and ``<table>`` blocks with one
``<tr>`` per line and only ``rowspan``/``colspan`` attributes.
"""

from __future__ import annotations

import gzip
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CHECKED_BOX_RE = re.compile(r"[□☐❏◻]\s?[Vv√✓✔]")
# A few HWP files carry broken UTF-16 pairs; a lone surrogate cannot be written as UTF-8.
LONE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")
SECTION_NUMBER_RE = re.compile(r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]{1,4}|\d{1,2}|[가-하])[.)]?$")
HEADING_BOX_MAX_CHARS = 40
TITLE_BOX_MAX_CHARS = 80
SMALL_NESTED_MAX_ROWS = 4
FRAME_DOMINANT_SHARE = 0.6
SMALL_NESTED_MAX_CHARS = 300


@dataclass
class Cell:
    text: str
    rowspan: int = 1
    colspan: int = 1
    header: bool = False


@dataclass
class Node:
    kind: str  # "heading" | "para" | "table"
    text: str = ""
    level: int = 0
    rows: list[list[Cell]] = field(default_factory=list)


def clean_text(value: str) -> str:
    text = str(value or "").replace("\\$", "$").replace(" ", " ")
    text = LONE_SURROGATE_RE.sub("", text)
    text = CHECKED_BOX_RE.sub("☑", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


# ----------------------------------------------------------------- grid ---
def anchor_rows(table: dict) -> list[list[tuple[int, int, dict]]]:
    """Span-anchor cells per row as ``(row, col, cell)``; covered placeholders are skipped."""

    cells = table.get("cells") or []
    covered: set[tuple[int, int]] = set()
    rows: list[list[tuple[int, int, dict]]] = []
    for r, row in enumerate(cells):
        anchors = []
        for c, cell in enumerate(row):
            if (r, c) in covered:
                continue
            rowspan = max(1, int(cell.get("rowSpan") or 1))
            colspan = max(1, int(cell.get("colSpan") or 1))
            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr or dc:
                        covered.add((r + dr, c + dc))
            anchors.append((r, c, cell))
        rows.append(anchors)
    return rows


def _has_nested_table(cell: dict) -> bool:
    return any(block.get("type") == "table" for block in cell.get("blocks") or [])


def _block_text(blocks: list[dict]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "table":
            for row in anchor_rows(block.get("table") or {}):
                parts.append(" ".join(clean_text(_cell_text(cell)) for _, _, cell in row))
        elif block.get("text"):
            parts.append(clean_text(block["text"]))
        for child in block.get("children") or []:
            parts.append(_block_text([child]))
    return "\n".join(part for part in parts if part)


def _cell_text(cell: dict) -> str:
    return _block_text(cell["blocks"]) if cell.get("blocks") else str(cell.get("text") or "")


def _nested_text_as_rows(blocks: list[dict]) -> str:
    """A small nested table kept inside a data cell, written as ``a | b | c`` lines."""

    lines: list[str] = []
    for block in blocks:
        if block.get("type") == "table":
            for row in anchor_rows(block.get("table") or {}):
                values = [clean_text(_cell_text(cell)).replace("\n", " ") for _, _, cell in row]
                values = [value for value in values if value]
                if values:
                    lines.append(" | ".join(values))
        elif block.get("text"):
            lines.append(clean_text(block["text"]))
        for child in block.get("children") or []:
            lines.append(_nested_text_as_rows([child]))
    return "\n".join(line for line in lines if line)


# ------------------------------------------------------------ flatten ---
def _is_frame(table: dict, rows: list[list[tuple[int, int, dict]]]) -> bool:
    """A layout frame around content, as opposed to a data table that holds a table.

    Frames are a single cell, or a few "label │ content" rows: the whole plan
    typed inside one box, "평가방법 및 채점기준 │ <rubric table>".  A table with
    more columns or rows is data even when one of its cells holds a table (a
    과제 표 whose 평가 기준 row carries the rubric); unwrapping it would scatter
    its label/value pairs into loose lines.
    """

    anchors = [cell for row in rows for _, _, cell in row]
    if not any(_has_nested_table(cell) for cell in anchors):
        return False
    if len(anchors) == 1:
        return True
    reasons = set((table.get("classification") or {}).get("reasons") or [])
    few_rows = len(rows) <= 3
    narrow = all(len(row) <= 2 for row in rows)
    # A title row, a 지도교사 row and one cell holding the whole plan (인천 부개고).
    lengths = [len(_cell_text(cell)) for cell in anchors]
    dominant = max(lengths) >= FRAME_DOMINANT_SHARE * (sum(lengths) or 1)
    return few_rows and (narrow or dominant or "nested-structure-wrapper" in reasons)


def _is_small_table(block: dict) -> bool:
    """A checkbox menu or similar short grid that reads fine as text inside its cell."""

    rows = anchor_rows(block.get("table") or {})
    text = sum(len(_cell_text(cell)) for row in rows for _, _, cell in row)
    return len(rows) <= SMALL_NESTED_MAX_ROWS and text <= SMALL_NESTED_MAX_CHARS


def _heading_box(rows: list[list[tuple[int, int, dict]]]) -> str:
    """Text of a one-row title box ("Ⅲ │ │ 수행 평가 세부 계획"), else ``""``."""

    if len(rows) != 1:
        return ""
    values = [clean_text(_cell_text(cell)).replace("\n", " ") for _, _, cell in rows[0]]
    values = [value for value in values if value]
    if not values or len(values) > 3:
        return ""
    joined = " ".join(values)
    if len(joined) > HEADING_BOX_MAX_CHARS:
        return ""
    if len(values) == 1 or SECTION_NUMBER_RE.match(values[0]):
        return joined
    return ""


def _paragraphs(text: str) -> list[Node]:
    return [Node("para", text=line) for line in clean_text(text).splitlines() if line.strip()]


def flatten_blocks(blocks: list[dict], depth: int = 0) -> list[Node]:
    nodes: list[Node] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "heading":
            text = clean_text(block.get("text") or "").replace("\n", " ")
            if text:
                nodes.append(Node("heading", text=text, level=max(1, min(6, int(block.get("level") or 2)))))
        elif kind in ("paragraph", "list"):
            nodes.extend(_paragraphs(block.get("text") or ""))
            if block.get("children"):
                nodes.extend(flatten_blocks(block["children"], depth))
        elif kind == "table":
            nodes.extend(_flatten_table(block.get("table") or {}, depth))
        # images and separators carry no plan text
    return nodes


def _flatten_table(table: dict, depth: int) -> list[Node]:
    rows = anchor_rows(table)
    if not any(row for row in rows):
        return []
    if depth < 8 and _is_frame(table, rows):
        nodes: list[Node] = []
        for row in rows:
            row_has_nested = any(_has_nested_table(cell) for _, _, cell in row)
            for _, _, cell in row:
                if cell.get("blocks"):
                    nodes.extend(flatten_blocks(cell["blocks"], depth + 1))
                    continue
                text = clean_text(cell.get("text") or "")
                if not text:
                    continue
                # The label beside a nested table ("평가방법\n및\n채점기준") is that
                # table's title; frames break such labels over several lines.
                label = " ".join(text.split())
                if row_has_nested and len(label) <= 30:
                    nodes.append(Node("heading", text=label, level=4))
                else:
                    nodes.extend(_paragraphs(text))
        return nodes
    title = _heading_box(rows)
    if title:
        return [Node("heading", text=title, level=2)]
    anchors = [cell for row in rows for _, _, cell in row]
    if len(anchors) == 1 and not _has_nested_table(anchors[0]):
        text = clean_text(_cell_text(anchors[0]))
        if not text:
            return []
        # A title box breaks its title over lines ("…생명과학II과 교수ㆍ학습 및" /
        # "평가 운영 계획"); a short box is one title, a long one is prose.
        lines = text.splitlines()
        joined = " ".join(" ".join(lines).split())
        if len(lines) <= 3 and len(joined) <= TITLE_BOX_MAX_CHARS:
            return [Node("heading", text=joined, level=3)]
        return _paragraphs(text)
    grid: list[list[Cell]] = []
    hoisted: list[Node] = []
    has_header_row = bool(table.get("hasHeader"))
    for row in rows:
        out_row = []
        row_label = " ".join(clean_text(_cell_text(row[0][2])).split()) if row else ""
        for r, _, cell in row:
            blocks = cell.get("blocks") or []
            big = [block for block in blocks if block.get("type") == "table" and not _is_small_table(block)]
            if big and depth < 8:
                # A rubric inside the 과제 표: keep the outer grid, publish the
                # rubric as its own table right after it, under its row label.
                rest = [block for block in blocks if block not in big]
                text = _nested_text_as_rows(rest)
                if row_label and len(row_label) <= 30 and row_label != clean_text(text):
                    hoisted.append(Node("para", text=row_label))
                for block in big:
                    hoisted.extend(_flatten_table(block.get("table") or {}, depth + 1))
            elif blocks:
                text = _nested_text_as_rows(blocks)
            else:
                text = clean_text(cell.get("text") or "")
            out_row.append(Cell(
                text=clean_text(text),
                rowspan=max(1, int(cell.get("rowSpan") or 1)),
                colspan=max(1, int(cell.get("colSpan") or 1)),
                header=bool(cell.get("isHeader")) or (r == 0 and has_header_row),
            ))
        grid.append(out_row)
    _clamp_spans(grid, len(rows))
    return [Node("table", rows=grid), *hoisted]


def _clamp_spans(grid: list[list[Cell]], row_count: int) -> None:
    for index, row in enumerate(grid):
        for cell in row:
            cell.rowspan = max(1, min(cell.rowspan, row_count - index, 50))
            cell.colspan = max(1, min(cell.colspan, 50))


# ------------------------------------------------------------- render ---
def _cell_html(cell: Cell) -> str:
    tag = "th" if cell.header else "td"
    attrs = ""
    if cell.rowspan > 1:
        attrs += f' rowspan="{cell.rowspan}"'
    if cell.colspan > 1:
        attrs += f' colspan="{cell.colspan}"'
    body = "<br>".join(html.escape(line, quote=False) for line in cell.text.splitlines())
    return f"<{tag}{attrs}>{body}</{tag}>"


def table_html(rows: list[list[Cell]]) -> str:
    lines = ["<table>"]
    for row in rows:
        lines.append("<tr>" + "".join(_cell_html(cell) for cell in row) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def flow_text(nodes: list[Node]) -> str:
    parts: list[str] = []
    for node in nodes:
        if node.kind == "heading":
            parts.append(f"{'#' * node.level} {node.text}")
        elif node.kind == "para":
            parts.append(node.text)
        elif node.kind == "table" and node.rows:
            parts.append(table_html(node.rows))
    return "\n\n".join(parts)


# -------------------------------------------------------------- store ---
def member_blocks(store: Path, sha: str, index: int) -> list[dict]:
    path = store / sha[:2] / sha / f"{index}.json.gz"
    if not path.is_file():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return list(json.load(handle).get("blocks") or [])


def document_flow_text(record: dict, store: Path) -> str:
    """Parser input for one stored document; ZIP members keep the ``[zip:…][…]`` markers."""

    members = record.get("members") or []
    sha = str(record.get("sha256") or "")
    if record.get("format") == "zip":
        parts = []
        for member in members:
            body = ""
            if member.get("status") in ("ok", "short"):
                body = flow_text(flatten_blocks(member_blocks(store, sha, int(member["index"]))))
            parts.append(f"[zip:{member['name']}][{member.get('status')}]\n{body}".rstrip())
        return "\n\n".join(parts)
    if not members or members[0].get("status") not in ("ok", "short"):
        return ""
    return flow_text(flatten_blocks(member_blocks(store, sha, 0)))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Print the parser input text of one stored document")
    parser.add_argument("sha256")
    parser.add_argument("--store", type=Path, default=Path(__file__).resolve().parents[1] / "data/derived/kordoc")
    args = parser.parse_args()
    doc = json.loads((args.store / args.sha256[:2] / args.sha256 / "doc.json").read_text("utf-8"))
    print(document_flow_text(doc, args.store))
