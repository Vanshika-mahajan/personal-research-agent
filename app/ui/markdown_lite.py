"""
A small, safe Markdown -> HTML renderer for the reports.

Reports quote text from the web, so **nothing is trusted**: every piece of
text is HTML-escaped first and formatting is added afterwards. Links are only
made for http(s) addresses. No raw HTML in the input ever reaches the output.

Supported (everything the reports use): headings, paragraphs, bold, italic,
`code`, links, blockquotes, bullet / numbered lists (nested by indentation),
tables, horizontal rules and fenced code blocks.
"""

from __future__ import annotations

import html
import re
from typing import List

_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_FENCE = re.compile(r"^\s*```")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")

_MAX_DEPTH = 4


def inline(text: str) -> str:
    """Escape, then apply bold / italic / code / links."""

    text = (text or "").replace("\x00", "")

    codes: List[str] = []

    def stash(match):
        codes.append(html.escape(match.group(1)))
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(stash, text)
    text = html.escape(text)

    def link(match):
        label, url = match.group(1), match.group(2)

        if re.match(r"^https?://", url, re.I):
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'

        return label

    text = _LINK.sub(link, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)


def _cells(line: str) -> List[str]:
    line = line.strip()

    if line.startswith("|"):
        line = line[1:]

    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]

    return [cell.strip().replace("\\|", "|") for cell in _UNESCAPED_PIPE.split(line)]


def _aligns(separator: str) -> List[str]:
    out = []

    for cell in _cells(separator):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else "right" if right else "left" if left else "")

    return out


def _is_table_start(lines: List[str], i: int) -> bool:
    return (
        i + 1 < len(lines)
        and "|" in lines[i]
        and bool(_TABLE_SEP.match(lines[i + 1]))
        and "-" in lines[i + 1]
    )


def _starts_block(lines: List[str], i: int) -> bool:
    line = lines[i]

    return bool(
        _HEADING.match(line)
        or _RULE.match(line)
        or _ITEM.match(line)
        or _FENCE.match(line)
        or line.lstrip().startswith(">")
        or _is_table_start(lines, i)
    )


def _table(lines: List[str], i: int):
    header = _cells(lines[i])
    aligns = _aligns(lines[i + 1])

    def attr(index):
        align = aligns[index] if index < len(aligns) else ""
        return f' style="text-align:{align}"' if align else ""

    out = ['<div class="table-wrap"><table><thead><tr>']

    for index, cell in enumerate(header):
        out.append(f"<th{attr(index)}>{inline(cell)}</th>")

    out.append("</tr></thead><tbody>")

    i += 2

    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        out.append("<tr>")

        for index, cell in enumerate(_cells(lines[i])):
            out.append(f"<td{attr(index)}>{inline(cell)}</td>")

        out.append("</tr>")
        i += 1

    out.append("</tbody></table></div>")

    return "".join(out), i


def _list(lines: List[str], i: int):
    """Nested lists, by indentation. Returns (html, next index)."""

    items = []  # (indent, ordered, text)

    while i < len(lines):
        match = _ITEM.match(lines[i])

        if match:
            indent = len(match.group(1).replace("\t", "    "))
            items.append([indent, match.group(2)[0].isdigit(), match.group(3)])
            i += 1
            continue

        # an indented line right after an item continues that item
        if items and lines[i].strip() and lines[i].startswith((" ", "\t")) and not _starts_block(lines, i):
            items[-1][2] += " " + lines[i].strip()
            i += 1
            continue

        break

    out: List[str] = []
    stack: List[tuple] = []  # (indent, tag)

    for indent, ordered, text in items:
        tag = "ol" if ordered else "ul"

        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")

        if stack and indent == stack[-1][0]:
            out.append("</li>")
        elif not stack or indent > stack[-1][0]:
            out.append(f"<{tag}>")
            stack.append((indent, tag))

        out.append(f"<li>{inline(text)}")

    while stack:
        out.append(f"</li></{stack.pop()[1]}>")

    return "".join(out), i


def render(markdown: str, _depth: int = 0) -> str:
    """Markdown text -> safe HTML."""

    lines = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    out: List[str] = []

    i = 0

    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        if _FENCE.match(line):
            code = []
            i += 1

            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1

            i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue

        heading = _HEADING.match(line)

        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if _RULE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if _is_table_start(lines, i):
            block, i = _table(lines, i)
            out.append(block)
            continue

        if line.lstrip().startswith(">") and _depth < _MAX_DEPTH:
            quote = []

            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1

            out.append(f"<blockquote>{render(chr(10).join(quote), _depth + 1)}</blockquote>")
            continue

        if _ITEM.match(line):
            block, i = _list(lines, i)
            out.append(block)
            continue

        paragraph = [line.strip()]
        i += 1

        while i < len(lines) and lines[i].strip() and not _starts_block(lines, i):
            paragraph.append(lines[i].strip())
            i += 1

        out.append(f"<p>{inline(' '.join(paragraph))}</p>")

    return "\n".join(out)


def title_of(markdown: str, fallback: str = "") -> str:
    """First heading of a document, as plain text."""

    for line in (markdown or "").splitlines():
        match = _HEADING.match(line)

        if match:
            return re.sub(r"[*`_]", "", match.group(2)).strip() or fallback

    return fallback
