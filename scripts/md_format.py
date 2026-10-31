"""Markdown formatting rules checked by scripts/lint.py (pure Python, standard library only).

Rules, each finding is (line, message):

1. LF line endings only: no carriage return.
2. The file is not empty and ends with exactly one newline.
3. Lines are at most MAX_LINE characters, except
   - table rows (the first non-blank character is `|`),
   - lines inside a fenced code block (``` or ~~~), fence lines included,
   - lines that cannot be wrapped: after the indentation, blockquote marker and list marker there
     is no space at or before column MAX_LINE, so there is no place to break (a long URL or path
     alone on a line). A line with a space in reach can be wrapped, so it is a finding even when
     its overflow is one long word.

Trailing whitespace is not checked, and nothing here rewraps prose: fix_bytes repairs only the
line endings and the final newline.
"""

import re

MAX_LINE = 120

# Indentation, blockquote markers, then one list marker (-, *, + or 1. / 1)) and its spaces.
_PREFIX = re.compile(r"^(?:\s*>)*\s*(?:(?:[-*+]|\d{1,9}[.)])\s+)?")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def _can_wrap(line: str) -> bool:
    """True when a space within reach of column MAX_LINE gives a break that fits."""
    start = _PREFIX.match(line).end()
    return " " in line[start : MAX_LINE + 1]


def check_text(text: str) -> list[tuple[int, str]]:
    """The findings in a decoded Markdown file, in line order."""
    if not text:
        return [(1, "file is empty")]
    findings: list[tuple[int, str]] = []
    lines = text.split("\n")
    fence: str | None = None  # the opening fence run while inside a code block
    for number, raw in enumerate(lines, start=1):
        line = raw.removesuffix("\r")
        if "\r" in raw:
            findings.append((number, "carriage return (use LF line endings)"))
        marker = _FENCE.match(line)
        if fence is not None:
            closes = (
                marker
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and line.strip() == marker.group(1)
            )
            if closes:
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            continue
        if line.lstrip().startswith("|"):
            continue
        length = len(line.rstrip())
        if length > MAX_LINE and _can_wrap(line.rstrip()):
            findings.append(
                (number, f"line is {length} characters (maximum {MAX_LINE})")
            )
    if not text.endswith("\n"):
        findings.append((len(lines), "no newline at the end of the file"))
    elif text.endswith(("\n\n", "\n\r\n")):
        findings.append(
            (len(lines) - 1, "more than one newline at the end of the file")
        )
    return findings


def check_bytes(data: bytes) -> list[tuple[int, str]]:
    """The findings in a raw Markdown file, in line order."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return [(1, f"not valid UTF-8: {error}")]
    return check_text(text)


def fix_bytes(data: bytes) -> bytes:
    """CRLF to LF and exactly one final newline. Prose is never rewrapped."""
    fixed = data.replace(b"\r\n", b"\n")
    if not fixed.strip():
        return data
    return fixed.rstrip(b"\n") + b"\n"
