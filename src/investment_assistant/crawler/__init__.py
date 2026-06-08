"""Crawler exploration-control package.

This package does not crawl the open web on its own. It supplies the parts the
design note identifies as genuinely new: structural guardrails and link triage.
Fetching, robots.txt, rate limiting, and storage are reused from the existing
:mod:`investment_assistant.ingestion` and :mod:`investment_assistant.rag` layers.

- Phase 1 (:mod:`~investment_assistant.crawler.policy`): domain/prefix locks,
  a visited set, and depth/page/time ceilings — the boundary that makes
  off-target crawling structurally impossible.
- Phase 2 (:mod:`~investment_assistant.crawler.extract`): link extraction,
  target-page scoring, and thin-page quarantine — descending from a table of
  contents toward dividend/financial body pages.
- Phase 3 (:mod:`~investment_assistant.crawler.frontier`): targeted BFS that
  composes the guardrails and triage into a guided crawl from the IR top page.
"""

from investment_assistant.crawler.extract import (
    EXCLUDE_KEYWORDS,
    TARGET_KEYWORDS,
    Link,
    PageAssessment,
    ScoredLink,
    assess_page,
    count_target_keywords,
    extract_body_text,
    extract_links,
    rank_links,
    score_link,
)
from investment_assistant.crawler.frontier import (
    CrawledPage,
    CrawlReport,
    FetchedPage,
    crawl,
)
from investment_assistant.crawler.policy import (
    CrawlLimits,
    CrawlPolicy,
    UrlDecision,
)
from investment_assistant.crawler.registry import build_crawl_targets_from_registry

__all__ = [
    "EXCLUDE_KEYWORDS",
    "TARGET_KEYWORDS",
    "CrawlLimits",
    "CrawlPolicy",
    "CrawlReport",
    "CrawledPage",
    "FetchedPage",
    "Link",
    "PageAssessment",
    "ScoredLink",
    "UrlDecision",
    "assess_page",
    "build_crawl_targets_from_registry",
    "count_target_keywords",
    "crawl",
    "extract_body_text",
    "extract_links",
    "rank_links",
    "score_link",
]
