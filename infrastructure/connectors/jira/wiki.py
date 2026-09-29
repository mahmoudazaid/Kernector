"""Bounded Jira wiki markup (Data Center / Server) to Markdown converter.

Covers the subset issues commonly use; anything else stays literal text.
Nothing is evaluated: macros are never interpreted.
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"h([1-6])\.\s+(.*)")
_LIST_ITEM = re.compile(r"([*#]+)\s+(.*)")
_MAX_LIST_DEPTH = 6
_MARKER_WIDTH = {"*": 2, "#": 3}
_VERBATIM_OPEN = re.compile(r"\{(code|noformat)(?::([^}]*))?\}")
_LANGUAGE = re.compile(r"[A-Za-z0-9_+#.-]{1,32}")
_BACKTICK_RUN = re.compile(r"`+")
_BOLD = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]*?\S)\*(?![\w*])")
_ITALIC = re.compile(r"(?<![\w_])_(?=\S)([^_\n]*?\S)_(?![\w_])")
_SAFE_URL = re.compile(r"(?:https?://|mailto:)[^\s<>()\[\]]+", re.IGNORECASE)
_USER = re.compile(r"[\w.@+-]{1,128}")


def wiki_to_markdown(raw: object) -> str:
    """Render Jira wiki markup as Markdown; non-strings render as ``""``."""
    if not isinstance(raw, str):
        return ""
    blocks: list[tuple[str, list[str]]] = []
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        verbatim = _VERBATIM_OPEN.match(stripped)
        if verbatim:
            index = _verbatim_block(blocks, verbatim, stripped, lines, index)
            continue
        if not stripped:
            blocks.append(("blank", []))
            continue
        heading = _HEADING.fullmatch(stripped)
        if heading:
            level = int(heading.group(1))
            blocks.append(("heading", [f"{'#' * level} {_inline(heading.group(2).strip())}"]))
            continue
        if stripped.startswith("|"):
            _append(blocks, "table", stripped)
            continue
        item = _LIST_ITEM.fullmatch(stripped)
        if item:
            _append(blocks, "list", _list_line(item.group(1), item.group(2)))
            continue
        _append(blocks, "paragraph", _inline(stripped))
    return _join(blocks)


def _verbatim_block(
    blocks: list[tuple[str, list[str]]],
    opening: re.Match[str],
    stripped: str,
    lines: list[str],
    index: int,
) -> int:
    """Consume a ``{code}``/``{noformat}`` block; unterminated blocks end at EOF."""
    name = opening.group(1)
    closing = "{" + name + "}"
    content: list[str] = []
    trailing = ""
    rest = stripped[opening.end():]
    end = rest.find(closing)
    if end >= 0:
        content.append(rest[:end])
        trailing = rest[end + len(closing):].strip()
    else:
        if rest.strip():
            content.append(rest)
        while index < len(lines):
            line = lines[index]
            index += 1
            end = line.find(closing)
            if end >= 0:
                if line[:end].strip():
                    content.append(line[:end])
                trailing = line[end + len(closing):].strip()
                break
            content.append(line)
    body = "\n".join(content)
    longest = max((len(run) for run in _BACKTICK_RUN.findall(body)), default=0)
    fence = "`" * max(3, longest + 1)
    language = _language(opening.group(2)) if name == "code" else ""
    blocks.append(("code", [f"{fence}{language}", *content, fence]))
    if trailing:
        _append(blocks, "paragraph", _inline(trailing))
    return index


def _language(params: str | None) -> str:
    if not params:
        return ""
    parts = [part.strip() for part in params.split("|")]
    for part in parts:
        key, sep, value = part.partition("=")
        if sep and key.strip() == "language":
            candidate = value.strip()
            break
    else:
        candidate = "" if "=" in parts[0] else parts[0]
    return candidate if _LANGUAGE.fullmatch(candidate) else ""


def _list_line(markers: str, text: str) -> str:
    markers = markers[:_MAX_LIST_DEPTH]
    indent = sum(_MARKER_WIDTH[marker] for marker in markers[:-1])
    bullet = "1." if markers[-1] == "#" else "-"
    return f"{' ' * indent}{bullet} {_inline(text.strip())}"


def _append(blocks: list[tuple[str, list[str]]], kind: str, line: str) -> None:
    if blocks and blocks[-1][0] == kind:
        blocks[-1][1].append(line)
    else:
        blocks.append((kind, [line]))


def _join(blocks: list[tuple[str, list[str]]]) -> str:
    rendered = [
        _table(lines) if kind == "table" else "\n".join(lines)
        for kind, lines in blocks
        if kind != "blank"
    ]
    return "\n\n".join(chunk for chunk in rendered if chunk)


def _table(rows: list[str]) -> str:
    cells = [_cells(row) for row in rows]
    width = max(len(row) for row in cells)
    padded = [row + [""] * (width - len(row)) for row in cells]
    lines = [_table_row(padded[0]), _table_row(["---"] * width)]
    lines.extend(_table_row(row) for row in padded[1:])
    return "\n".join(lines)


def _table_row(cells: list[str]) -> str:
    return f"| {' | '.join(cells)} |"


def _cells(row: str) -> list[str]:
    """Split a ``||header||`` or ``|cell|`` row, ignoring pipes inside ``[...]``."""
    separator = "||" if row.startswith("||") else "|"
    body = row[len(separator):]
    if body.endswith(separator):
        body = body[: -len(separator)]
    cells: list[str] = []
    current: list[str] = []
    in_link = False
    position = 0
    while position < len(body):
        char = body[position]
        if char == "[":
            in_link = True
        elif char == "]":
            in_link = False
        elif not in_link and body.startswith(separator, position):
            cells.append("".join(current).strip())
            current = []
            position += len(separator)
            continue
        current.append(char)
        position += 1
    cells.append("".join(current).strip())
    return [_inline(cell) for cell in cells]


def _inline(text: str) -> str:
    """Render links, mentions, monospace and emphasis in one linear pass."""
    rendered: list[str] = []
    plain: list[str] = []
    position = 0
    bracket_end: int | None = None
    mono_end: int | None = None
    while position < len(text):
        if text.startswith("{{", position):
            if mono_end is None or (0 <= mono_end < position + 2):
                mono_end = text.find("}}", position + 2)
            if mono_end > position + 2:
                rendered.extend((_emphasis("".join(plain)), _monospace(text[position + 2 : mono_end])))
                plain = []
                position = mono_end + 2
                continue
        if text[position] == "[":
            if bracket_end is None or (0 <= bracket_end < position):
                bracket_end = text.find("]", position + 1)
            if bracket_end > position:
                link = _bracket(text[position + 1 : bracket_end])
                if link is not None:
                    rendered.extend((_emphasis("".join(plain)), link))
                    plain = []
                    position = bracket_end + 1
                    continue
        plain.append(text[position])
        position += 1
    rendered.append(_emphasis("".join(plain)))
    return "".join(rendered)


def _emphasis(text: str) -> str:
    text = _BOLD.sub(r"**\1**", text)
    return _ITALIC.sub(r"*\1*", text)


def _monospace(code: str) -> str:
    longest = max((len(run) for run in _BACKTICK_RUN.findall(code)), default=0)
    ticks = "`" * (longest + 1)
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{ticks}{pad}{code}{pad}{ticks}"


def _bracket(inner: str) -> str | None:
    """Render ``[~user]``, ``[text|url]`` or ``[url]``; ``None`` keeps it literal."""
    if inner.startswith("~"):
        user = inner[1:].strip()
        return f"@{user}" if _USER.fullmatch(user) else None
    if "|" in inner:
        label, url = (part.strip() for part in inner.split("|")[:2])
        if not _SAFE_URL.fullmatch(url):
            return _emphasis(label)
        return f"[{_emphasis(label)}]({url})" if label else f"<{url}>"
    url = inner.strip()
    return f"<{url}>" if _SAFE_URL.fullmatch(url) else None
