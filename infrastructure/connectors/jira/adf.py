"""Render Atlassian Document Format (ADF) as plain markdown."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_INLINE_MARKS = {"strong": "**", "em": "*", "code": "`", "strike": "~~"}


def adf_to_markdown(node: object) -> str:
    """Return markdown for an ADF document; plain strings pass through."""
    if isinstance(node, str):
        return node.strip()
    if not isinstance(node, Mapping):
        return ""
    return "\n\n".join(_blocks(_children(node))).strip()


def _blocks(nodes: Sequence[Mapping[str, object]]) -> list[str]:
    rendered = (_block(node) for node in nodes)
    return [block for block in rendered if block]


def _block(node: Mapping[str, object]) -> str:
    kind = node.get("type")
    if kind == "paragraph":
        return _inline(_children(node))
    if kind == "heading":
        level = _attr(node, "level")
        depth = level if isinstance(level, int) and 1 <= level <= 6 else 1
        return f"{'#' * depth} {_inline(_children(node))}"
    if kind in {"bulletList", "orderedList"}:
        return _list(node, ordered=kind == "orderedList")
    if kind == "codeBlock":
        language = _attr(node, "language")
        fence = f"```{language}" if isinstance(language, str) else "```"
        return "\n".join([fence, _plain(_children(node)), "```"])
    if kind == "blockquote":
        inner = "\n\n".join(_blocks(_children(node)))
        return "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
    if kind == "rule":
        return "---"
    if kind == "table":
        return _table(node)
    if kind in {"media", "mediaSingle", "mediaGroup"}:
        return ""
    if kind == "text" or kind in _INLINE_NODE_TYPES:
        return _inline([node])
    return "\n\n".join(_blocks(_children(node)))


def _list(node: Mapping[str, object], *, ordered: bool) -> str:
    lines: list[str] = []
    for index, item in enumerate(_children(node), start=1):
        marker = f"{index}." if ordered else "-"
        body = "\n".join(_blocks(_children(item)))
        item_lines = body.splitlines() or [""]
        lines.append(f"{marker} {item_lines[0]}")
        lines.extend(f"  {line}" for line in item_lines[1:])
    return "\n".join(lines)


def _table(node: Mapping[str, object]) -> str:
    rows: list[str] = []
    for row in _children(node):
        cells = [" ".join(_blocks(_children(cell))) for cell in _children(row)]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


_INLINE_NODE_TYPES = {"hardBreak", "mention", "emoji", "inlineCard", "status", "date"}


def _inline(nodes: Sequence[Mapping[str, object]]) -> str:
    return "".join(_inline_one(node) for node in nodes)


def _inline_one(node: Mapping[str, object]) -> str:
    kind = node.get("type")
    if kind == "text":
        return _marked(node)
    if kind == "hardBreak":
        return "\n"
    if kind in {"mention", "status"}:
        return _text_attr(node, "text")
    if kind == "emoji":
        return _text_attr(node, "text") or _text_attr(node, "shortName")
    if kind == "inlineCard":
        return _text_attr(node, "url")
    if kind == "date":
        return _text_attr(node, "timestamp")
    return _inline(_children(node))


def _marked(node: Mapping[str, object]) -> str:
    text = node.get("text")
    if not isinstance(text, str):
        return ""
    marks = node.get("marks")
    if not isinstance(marks, Sequence) or isinstance(marks, (str, bytes)):
        return text
    href: str | None = None
    for mark in marks:
        if not isinstance(mark, Mapping):
            continue
        wrapper = _INLINE_MARKS.get(str(mark.get("type")))
        if wrapper:
            text = f"{wrapper}{text}{wrapper}"
        elif mark.get("type") == "link":
            candidate = _attr(mark, "href")
            href = candidate if isinstance(candidate, str) else None
    return f"[{text}]({href})" if href else text


def _plain(nodes: Sequence[Mapping[str, object]]) -> str:
    return "".join(
        node["text"] if isinstance(node.get("text"), str) else _plain(_children(node))
        for node in nodes
    )


def _children(node: Mapping[str, object]) -> list[Mapping[str, object]]:
    content = node.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return []
    return [child for child in content if isinstance(child, Mapping)]


def _attr(node: Mapping[str, object], name: str) -> object:
    attrs = node.get("attrs")
    return attrs.get(name) if isinstance(attrs, Mapping) else None


def _text_attr(node: Mapping[str, object], name: str) -> str:
    value = _attr(node, name)
    return value if isinstance(value, str) else ""
