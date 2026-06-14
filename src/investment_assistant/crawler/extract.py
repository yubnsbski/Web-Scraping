"""Link extraction, target-page scoring, and quarantine (Phase 2).

No network I/O. Operates on already-fetched HTML/text. The job here is to turn a
"table of contents" page into a ranked set of links that head toward the pages
we actually want (dividend policy, shareholder returns, financial highlights),
and to quarantine thin pages (navigation/index shells) so they never pollute the
RAG store.

Body-text extraction reuses :func:`extract_text_from_html` from the ingestion
layer rather than re-implementing HTML stripping.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from investment_assistant.ingestion.html_extract import extract_text_from_html

__all__ = [
    "ASSET_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    "EXCLUDE_KEYWORDS",
    "TARGET_KEYWORDS",
    "Link",
    "PageAssessment",
    "ScoredLink",
    "assess_page",
    "count_target_keywords",
    "extract_body_text",
    "extract_links",
    "link_kind",
    "rank_links",
    "score_link",
]

# Anchor/URL signals that a link heads toward a target page (§3.1 of the design
# note): dividend policy / shareholder returns and financial disclosure.
TARGET_KEYWORDS: tuple[str, ...] = (
    "配当",
    "株主還元",
    "配当性向",
    "配当方針",
    "dividend",
    "doe",
    "財務",
    "決算",
    "ハイライト",
    "financial",
    "有価証券報告書",
    "決算短信",
    "統合報告書",
)

# Anchor/URL signals that a link heads somewhere we do not want to descend into.
EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "採用",
    "recruit",
    "お知らせ",
    "ニュース",
    "news",
    "サイトマップ",
    "sitemap",
    "お問い合わせ",
    "contact",
    "個人情報",
    "privacy",
)

TARGET_WEIGHT = 1.0
EXCLUDE_PENALTY = 2.0
DEFAULT_MIN_CHARS = 800
DEFAULT_MIN_KEYWORD_HITS = 1

# Non-HTML asset links the crawler must never descend into as pages (they waste
# the per-page link budget and a fetch, and yield garbage when parsed as HTML).
ASSET_EXTENSIONS: tuple[str, ...] = (
    ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".ico", ".bmp", ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".webm", ".mov", ".avi", ".mp3", ".wav",
)
# Document links worth surfacing (IR 決算短信 / 有価証券報告書 / 統合報告書 are usually
# PDFs) but not parseable as HTML — recorded separately rather than crawled.
DOCUMENT_EXTENSIONS: tuple[str, ...] = (
    ".pdf", ".xls", ".xlsx", ".csv", ".doc", ".docx", ".ppt", ".pptx", ".zip",
)


def link_kind(url: str) -> str:
    """Classify a link as ``"page"``, ``"document"`` (PDF/Excel/…) or ``"asset"``.

    Based on the URL path extension, so the frontier can crawl only HTML pages,
    surface documents for separate handling, and drop static assets entirely.
    """

    path = urlsplit(url).path.lower()
    if path.endswith(ASSET_EXTENSIONS):
        return "asset"
    if path.endswith(DOCUMENT_EXTENSIONS):
        return "document"
    return "page"


@dataclass(frozen=True)
class Link:
    """An absolute link discovered on a page, with its anchor text."""

    url: str
    anchor_text: str


@dataclass(frozen=True)
class ScoredLink:
    """A link scored for how likely it leads to a target page."""

    url: str
    anchor_text: str
    score: float
    matched_targets: tuple[str, ...]
    matched_excludes: tuple[str, ...]


@dataclass(frozen=True)
class PageAssessment:
    """Quarantine verdict for a fetched page's body text."""

    is_substantive: bool
    char_count: int
    keyword_hits: int
    reason: str


class _LinkParser(HTMLParser):
    """Collect ``(href, anchor_text)`` pairs from anchor elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value.strip()
                break
        if not href:
            return
        # Flush any anchor that was left open (malformed/nested markup).
        self._flush()
        self._current_href = href
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._current_href is None:
            return
        text = " ".join("".join(self._current_text).split())
        self.links.append((self._current_href, text))
        self._current_href = None
        self._current_text = []


def extract_links(html: str, base_url: str) -> list[Link]:
    """Extract absolute http(s) links from ``html``, resolved against ``base_url``.

    Fragments are dropped and duplicate URLs are collapsed (first anchor text
    wins) so the frontier does not re-queue the same page under ``#section``
    variations.
    """

    parser = _LinkParser()
    parser.feed(html)
    parser.close()

    results: list[Link] = []
    seen: set[str] = set()
    for href, anchor_text in parser.links:
        absolute, _fragment = urldefrag(urljoin(base_url, href))
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        results.append(Link(url=absolute, anchor_text=anchor_text))
    return results


def score_link(link: Link) -> ScoredLink:
    """Score a link by target/exclude keyword hits in its anchor text and URL."""

    haystack = f"{link.anchor_text}\n{link.url}".lower()
    targets = _matched_keywords(haystack, TARGET_KEYWORDS)
    excludes = _matched_keywords(haystack, EXCLUDE_KEYWORDS)
    score = TARGET_WEIGHT * len(targets) - EXCLUDE_PENALTY * len(excludes)
    return ScoredLink(
        url=link.url,
        anchor_text=link.anchor_text,
        score=score,
        matched_targets=targets,
        matched_excludes=excludes,
    )


def rank_links(links: Iterable[Link]) -> list[ScoredLink]:
    """Score links and return them sorted by descending score (stable on ties)."""

    scored = [score_link(link) for link in links]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def count_target_keywords(text: str) -> int:
    """Return the number of distinct target keywords present in ``text``."""

    return len(_matched_keywords(text.lower(), TARGET_KEYWORDS))


def assess_page(
    text: str,
    *,
    min_chars: int = DEFAULT_MIN_CHARS,
    min_keyword_hits: int = DEFAULT_MIN_KEYWORD_HITS,
) -> PageAssessment:
    """Quarantine thin pages.

    A page is substantive if it has enough body text *or* carries at least the
    minimum number of target keywords. The initial criterion from the design
    note: under ``min_chars`` with zero target keywords is "thin" (a table of
    contents or empty shell) and is rejected before it reaches the RAG store.
    """

    char_count = len(text.strip())
    keyword_hits = count_target_keywords(text)
    if char_count >= min_chars:
        return PageAssessment(True, char_count, keyword_hits, "enough_text")
    if keyword_hits >= min_keyword_hits:
        return PageAssessment(True, char_count, keyword_hits, "keyword_match")
    return PageAssessment(False, char_count, keyword_hits, "thin_page")


def extract_body_text(html: str) -> str:
    """Reuse the ingestion HTML-to-text extractor for crawled bodies."""

    return extract_text_from_html(html)


def _matched_keywords(haystack: str, keywords: Iterable[str]) -> tuple[str, ...]:
    return tuple(keyword for keyword in keywords if keyword.lower() in haystack)
