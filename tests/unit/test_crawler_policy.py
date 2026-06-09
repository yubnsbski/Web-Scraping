from __future__ import annotations

import pytest

from investment_assistant.crawler.policy import (
    REASON_ALLOWED,
    REASON_ALREADY_VISITED,
    REASON_BLOCKED_SCHEME,
    REASON_DEPTH_EXCEEDED,
    REASON_OUTSIDE_DOMAINS,
    REASON_OUTSIDE_PREFIX,
    STOP_MAX_ELAPSED,
    STOP_MAX_PAGES,
    CrawlLimits,
    CrawlPolicy,
)


def _policy(**overrides: object) -> CrawlPolicy:
    kwargs: dict[str, object] = {
        "allowed_domains": ["www.mufg.jp"],
        "url_prefix": "https://www.mufg.jp/ir/",
        "limits": CrawlLimits(max_depth=2, max_pages=20),
    }
    kwargs.update(overrides)
    return CrawlPolicy(**kwargs)  # type: ignore[arg-type]


def test_allows_in_scope_url() -> None:
    decision = _policy().evaluate_url("https://www.mufg.jp/ir/dividend/", depth=1)
    assert decision.allowed
    assert decision.reason == REASON_ALLOWED


def test_rejects_external_domain() -> None:
    decision = _policy().evaluate_url("https://example.com/ir/dividend/", depth=1)
    assert not decision.allowed
    assert decision.reason == REASON_OUTSIDE_DOMAINS


def test_rejects_out_of_prefix_same_domain() -> None:
    # Same host, but /recruit/ is outside the /ir/ prefix lock.
    decision = _policy().evaluate_url("https://www.mufg.jp/recruit/", depth=1)
    assert not decision.allowed
    assert decision.reason == REASON_OUTSIDE_PREFIX


def test_rejects_non_http_scheme() -> None:
    decision = _policy().evaluate_url("mailto:ir@www.mufg.jp", depth=0)
    assert not decision.allowed
    assert decision.reason == REASON_BLOCKED_SCHEME


def test_rejects_depth_beyond_limit() -> None:
    decision = _policy().evaluate_url("https://www.mufg.jp/ir/dividend/", depth=3)
    assert not decision.allowed
    assert decision.reason == REASON_DEPTH_EXCEEDED


def test_visited_url_is_rejected_after_fetch() -> None:
    policy = _policy()
    url = "https://www.mufg.jp/ir/dividend/"
    assert policy.evaluate_url(url, depth=1).allowed
    policy.register_fetch(url)
    # Fragment-only variation normalizes to the same URL and is still blocked.
    again = policy.evaluate_url(url + "#section", depth=1)
    assert not again.allowed
    assert again.reason == REASON_ALREADY_VISITED


def test_normalize_url_lowercases_host_and_drops_fragment() -> None:
    normalized = CrawlPolicy.normalize_url("HTTPS://WWW.MUFG.JP/ir/Dividend/#anchor")
    assert normalized == "https://www.mufg.jp/ir/Dividend/"


def test_stops_at_max_pages() -> None:
    policy = _policy(limits=CrawlLimits(max_depth=2, max_pages=2))
    assert policy.can_fetch_more()
    policy.register_fetch("https://www.mufg.jp/ir/a/")
    assert policy.can_fetch_more()
    policy.register_fetch("https://www.mufg.jp/ir/b/")
    assert not policy.can_fetch_more()
    assert policy.stop_reason() == STOP_MAX_PAGES
    assert policy.pages_fetched == 2


def test_stops_at_max_elapsed_seconds() -> None:
    ticks = iter([100.0, 106.0])  # register_fetch start, then stop-check
    policy = _policy(
        limits=CrawlLimits(max_depth=2, max_pages=99, max_elapsed_seconds=5.0),
        clock=lambda: next(ticks),
    )
    policy.register_fetch("https://www.mufg.jp/ir/a/")
    assert policy.stop_reason() == STOP_MAX_ELAPSED


def test_empty_allowed_domains_is_rejected() -> None:
    with pytest.raises(ValueError, match="allowed_domains"):
        CrawlPolicy(allowed_domains=[], url_prefix="https://www.mufg.jp/ir/")


def test_from_registry_source_builds_locks_and_limits() -> None:
    policy = CrawlPolicy.from_registry_source(
        {
            "url": "https://www.mufg.jp/ir/",
            "allowed_domains": ["www.mufg.jp"],
            "url_prefix": "https://www.mufg.jp/ir/",
            "max_depth": 2,
            "max_pages": 20,
        }
    )
    assert policy.allowed_domains == frozenset({"www.mufg.jp"})
    assert policy.limits.max_depth == 2
    assert policy.limits.max_pages == 20
    assert policy.evaluate_url("https://www.mufg.jp/ir/dividend/", depth=1).allowed
    assert not policy.evaluate_url("https://www.mufg.jp/recruit/", depth=1).allowed


def test_from_registry_source_defaults_domain_to_start_host() -> None:
    policy = CrawlPolicy.from_registry_source({"url": "https://group.ntt/jp/ir/"})
    assert policy.allowed_domains == frozenset({"group.ntt"})
    # Prefix defaults to the start URL, so a sibling section is out of scope.
    assert not policy.evaluate_url("https://group.ntt/jp/recruit/", depth=1).allowed
