from __future__ import annotations

from investment_assistant.ingestion.fetcher import SafeFetcher
from investment_assistant.ingestion.http_cache import HttpCache
from investment_assistant.ingestion.rate_limit import DomainRateLimiter
from investment_assistant.ingestion.robots import RobotsChecker
from investment_assistant.ingestion.transport import HttpResponse


class FakeTransport:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        self.calls.append(url)
        return self.responses[url]


class FailingTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float, user_agent: str) -> HttpResponse:
        self.calls.append(url)
        msg = "network unavailable"
        raise OSError(msg)


def response(url: str, body: str, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        url=url,
        status_code=status_code,
        headers={"Content-Type": "text/plain; charset=utf-8"},
        body=body.encode(),
    )


def test_robots_checker_allows_url_when_robots_allows() -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        )
    })
    checker = RobotsChecker(transport, user_agent="investment-assistant-test")

    decision = checker.can_fetch("https://example.com/funds")

    assert decision.allowed is True
    assert decision.robots_url == "https://example.com/robots.txt"
    assert transport.calls == ["https://example.com/robots.txt"]


def test_robots_checker_blocks_url_when_robots_disallows() -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nDisallow: /private\n",
        )
    })
    checker = RobotsChecker(transport, user_agent="investment-assistant-test")

    decision = checker.can_fetch("https://example.com/private/report")

    assert decision.allowed is False
    assert decision.reason == "blocked_by_robots"


def test_domain_rate_limiter_waits_per_host() -> None:
    times = iter([10.0, 10.5, 11.0])
    waits: list[float] = []

    limiter = DomainRateLimiter(
        min_interval_seconds=1.0,
        clock=lambda: next(times),
        sleeper=waits.append,
    )

    first_wait = limiter.wait_for_url("https://example.com/a")
    second_wait = limiter.wait_for_url("https://example.com/b")

    assert first_wait == 0.0
    assert second_wait == 0.5
    assert waits == [0.5]


def test_safe_fetcher_dry_run_checks_robots_without_fetching_target(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        ),
    })
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch("https://example.com/funds", dry_run=True)

    assert result.source == "dry_run"
    assert result.allowed_by_robots is True
    assert result.status_code is None
    assert transport.calls == ["https://example.com/robots.txt"]


def test_safe_fetcher_uses_cache_after_first_network_fetch(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/funds": response("https://example.com/funds", "fund data"),
    })
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    first = fetcher.fetch("https://example.com/funds")
    second = fetcher.fetch("https://example.com/funds")

    assert first.source == "network"
    assert second.source == "cache"
    assert second.text_preview == "fund data"
    assert transport.calls == ["https://example.com/robots.txt", "https://example.com/funds"]


def test_safe_fetcher_saves_text_for_rag_indexing(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/funds": response(
            "https://example.com/funds",
            "# Fund page\n\nThis text can be indexed by local RAG.",
        ),
    })
    save_path = tmp_path / "local_docs" / "funds.txt"
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch("https://example.com/funds", save_text=save_path)

    assert result.source == "network"
    assert result.saved_path == str(save_path)
    assert save_path.read_text(encoding="utf-8") == (
        "# Fund page\n\nThis text can be indexed by local RAG."
    )


def test_safe_fetcher_does_not_save_text_for_dry_run(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        ),
    })
    save_path = tmp_path / "local_docs" / "dry-run.txt"
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch("https://example.com/funds", dry_run=True, save_text=save_path)

    assert result.source == "dry_run"
    assert result.saved_path is None
    assert not save_path.exists()


def test_safe_fetcher_extracts_html_text_before_preview_and_save(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/funds": response(
            "https://example.com/funds",
            "<html><head><title>Fund Page</title><style>.x{}</style></head>"
            "<body><h1>Overview</h1><p>Low cost &amp; diversified.</p>"
            "<script>hidden()</script></body></html>",
        ),
    })
    save_path = tmp_path / "local_docs" / "funds.txt"
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch(
        "https://example.com/funds",
        preview_chars=80,
        save_text=save_path,
        extract_text=True,
    )

    expected = "Fund Page\n\nOverview\nLow cost & diversified."
    assert result.source == "network"
    assert result.extracted_text is True
    assert result.text_preview == expected[:80]
    assert result.saved_path == str(save_path)
    assert save_path.read_text(encoding="utf-8") == expected


def test_safe_fetcher_includes_metadata_when_saving_text(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/funds": response(
            "https://example.com/funds",
            "<html><head><title>Fund Page</title></head><body><p>Visible text.</p></body></html>",
        ),
    })
    save_path = tmp_path / "local_docs" / "funds.txt"
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch(
        "https://example.com/funds",
        save_text=save_path,
        extract_text=True,
        include_metadata=True,
    )

    saved = save_path.read_text(encoding="utf-8")
    assert result.metadata_included is True
    assert saved.startswith("---\n")
    assert 'source_url: "https://example.com/funds"' in saved
    assert "fetched_at:" in saved
    assert "status_code: 200" in saved
    assert 'content_type: "text/plain; charset=utf-8"' in saved
    assert "extracted_text: true" in saved
    assert saved.endswith("Fund Page\n\nVisible text.")


def test_safe_fetcher_refuses_robots_blocked_target(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nDisallow: /blocked\n",
        ),
        "https://example.com/blocked": response("https://example.com/blocked", "blocked"),
    })
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch("https://example.com/blocked")

    assert result.source == "blocked_by_robots"
    assert result.allowed_by_robots is False
    assert transport.calls == ["https://example.com/robots.txt"]


def test_safe_fetcher_fetch_document_can_explicitly_skip_robots_gate(tmp_path) -> None:
    transport = FakeTransport({
        "https://example.com/robots.txt": response(
            "https://example.com/robots.txt",
            "User-agent: *\nDisallow: /blocked\n",
        ),
        "https://example.com/blocked": response("https://example.com/blocked", "market data"),
    })
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch_document("https://example.com/blocked", respect_robots=False)

    assert result.html == "market data"
    assert result.allowed_by_robots is True
    assert result.source == "network"
    assert transport.calls == ["https://example.com/robots.txt", "https://example.com/blocked"]


def test_safe_fetcher_fails_closed_when_robots_unavailable(tmp_path) -> None:
    transport = FailingTransport()
    fetcher = SafeFetcher(
        transport=transport,
        cache=HttpCache(tmp_path / "http.sqlite"),
        rate_limiter=DomainRateLimiter(min_interval_seconds=0),
        user_agent="investment-assistant-test",
    )

    result = fetcher.fetch("https://example.com/funds", dry_run=True)

    assert result.source == "robots_unavailable"
    assert result.allowed_by_robots is False
    assert result.status_code is None
    assert transport.calls == ["https://example.com/robots.txt"]
