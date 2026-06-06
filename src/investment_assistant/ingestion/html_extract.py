"""Small local HTML-to-text extraction helpers for safe ingestion."""

from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_SKIP_TAGS = frozenset({"script", "style", "noscript"})


class _TextExtractor(HTMLParser):
    """HTMLParser subclass that collects visible-ish text without network or LLM calls."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    @property
    def title(self) -> str:
        """Return the normalized document title."""

        return _normalize_text(" ".join(self._title_parts))

    @property
    def text(self) -> str:
        """Return normalized visible text."""

        body = _normalize_text("".join(self._parts))
        title = self.title
        if not title:
            return body
        if not body:
            return title
        first_line = body.splitlines()[0] if body else ""
        if first_line == title:
            return body
        return f"{title}\n\n{body}"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if normalized == "title":
            self._in_title = True
            return
        if self._skip_depth == 0 and normalized in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if normalized == "title":
            self._in_title = False
            return
        if self._skip_depth == 0 and normalized in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._parts.append(data)


def extract_text_from_html(html_text: str) -> str:
    """Extract normalized text from HTML using only the Python standard library."""

    parser = _TextExtractor()
    parser.feed(html_text)
    parser.close()
    return parser.text


def _normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\r", "\n").split("\n")]
    normalized_lines = [line for line in lines if line]
    return "\n".join(normalized_lines)
