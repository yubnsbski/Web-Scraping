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
from investment_assistant.crawler.policy import (
    CrawlLimits,
    CrawlPolicy,
    UrlDecision,
)

__all__ = [
    "EXCLUDE_KEYWORDS",
    "TARGET_KEYWORDS",
    "CrawlLimits",
    "CrawlPolicy",
    "Link",
    "PageAssessment",
    "ScoredLink",
    "UrlDecision",
    "assess_page",
    "count_target_keywords",
    "extract_body_text",
    "extract_links",
    "rank_links",
    "score_link",
]
