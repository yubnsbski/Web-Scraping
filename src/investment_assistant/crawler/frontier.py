"""Targeted breadth-first crawl (Phase 3).

Composes the Phase 1 guardrails (:mod:`~investment_assistant.crawler.policy`)
and Phase 2 link triage (:mod:`~investment_assistant.crawler.extract`) into a
guided depth-first-into-the-table-of-contents crawl: from a start page, follow
only the links that score as heading toward target pages (dividend policy /
financial disclosure), breadth-first, capped per level, until the policy's
depth/page/time ceilings stop it.

The fetch step is injected (``FetchFn``) so the frontier is fully testable
offline with canned HTML; the CLI supplies a real fetch backed by
:class:`~investment_assistant.ingestion.fetcher.SafeFetcher` (robots + cache +
rate limiting reused).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from investment_assistant.crawler.extract import (
    ScoredLink,
    assess_page,
    extract_body_text,
    extract_links,
    link_kind,
    rank_links,
)
from investment_assistant.crawler.policy import CrawlPolicy

DEFAULT_MAX_LINKS_PER_PAGE = 5


@dataclass(frozen=True)
class FetchedPage:
    """Result of fetching one URL during a crawl."""

    url: str
    allowed: bool
    html: str
    status_code: int | None = None


FetchFn = Callable[[str], FetchedPage]


@dataclass(frozen=True)
class CrawledPage:
    """A substantive page kept for RAG ingestion."""

    url: str
    depth: int
    text: str
    char_count: int
    keyword_hits: int


@dataclass
class CrawlReport:
    """Outcome of a crawl run, measured by target-page reach (not raw count)."""

    start_url: str
    fetched: int = 0
    target_pages: list[CrawledPage] = field(default_factory=list)
    documents: list[dict[str, object]] = field(default_factory=list)
    skipped: list[dict[str, object]] = field(default_factory=list)
    stop_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "start_url": self.start_url,
            "fetched": self.fetched,
            "target_pages_count": len(self.target_pages),
            "target_pages": [
                {
                    "url": page.url,
                    "depth": page.depth,
                    "char_count": page.char_count,
                    "keyword_hits": page.keyword_hits,
                }
                for page in self.target_pages
            ],
            "documents": self.documents,
            "skipped": self.skipped,
            "stop_reason": self.stop_reason,
        }


def crawl(
    policy: CrawlPolicy,
    *,
    start_url: str,
    fetch: FetchFn,
    max_links_per_page: int = DEFAULT_MAX_LINKS_PER_PAGE,
    min_link_score: float = 0.0,
) -> CrawlReport:
    """Run a targeted BFS crawl from ``start_url`` under ``policy``.

    Only links scoring above ``min_link_score`` are followed, top
    ``max_links_per_page`` per page, so the crawl descends from a table of
    contents toward target pages rather than fanning out indiscriminately.
    """

    start = policy.normalize_url(start_url)
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    enqueued: set[str] = {start}
    report = CrawlReport(start_url=start)

    while queue:
        if not policy.can_fetch_more():
            report.stop_reason = policy.stop_reason()
            break
        url, depth = queue.popleft()

        page = fetch(url)
        policy.register_fetch(url)
        report.fetched += 1

        if not page.allowed or not page.html:
            report.skipped.append({"url": url, "reason": "fetch_blocked_or_empty"})
            continue

        body = extract_body_text(page.html)
        assessment = assess_page(body)
        if assessment.is_substantive:
            report.target_pages.append(
                CrawledPage(
                    url=url,
                    depth=depth,
                    text=body,
                    char_count=assessment.char_count,
                    keyword_hits=assessment.keyword_hits,
                )
            )
        else:
            report.skipped.append(
                {"url": url, "reason": "thin_page", "char_count": assessment.char_count}
            )

        if depth >= policy.limits.max_depth:
            continue
        _enqueue_promising_links(
            policy,
            page,
            depth=depth,
            queue=queue,
            enqueued=enqueued,
            report=report,
            max_links_per_page=max_links_per_page,
            min_link_score=min_link_score,
        )

    if report.stop_reason is None and not policy.can_fetch_more():
        report.stop_reason = policy.stop_reason()
    return report


def _enqueue_promising_links(
    policy: CrawlPolicy,
    page: FetchedPage,
    *,
    depth: int,
    queue: deque[tuple[str, int]],
    enqueued: set[str],
    report: CrawlReport,
    max_links_per_page: int,
    min_link_score: float,
) -> None:
    added = 0
    for scored in rank_links(extract_links(page.html, page.url)):
        if added >= max_links_per_page:
            break
        if scored.score <= min_link_score:
            break  # ranked desc, so nothing below is promising either
        kind = link_kind(scored.url)
        if kind == "asset":
            continue  # never descend into css/js/images/fonts
        if kind == "document":
            _record_document(report, scored)
            continue  # PDFs etc. are terminal — surfaced, not crawled as HTML
        decision = policy.evaluate_url(scored.url, depth=depth + 1)
        if not decision.allowed or decision.url in enqueued:
            continue
        enqueued.add(decision.url)
        queue.append((decision.url, depth + 1))
        added += 1


def _record_document(report: CrawlReport, scored: ScoredLink) -> None:
    """Record a promising non-HTML document link once (dedup by URL)."""

    if any(doc.get("url") == scored.url for doc in report.documents):
        return
    report.documents.append(
        {"url": scored.url, "anchor_text": scored.anchor_text, "score": scored.score}
    )
