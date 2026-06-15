from __future__ import annotations

from investment_assistant.crawler.frontier import FetchedPage, crawl
from investment_assistant.crawler.policy import CrawlLimits, CrawlPolicy

# Start page anchors carry target/exclude signals via URL only, so the table of
# contents itself stays "thin" (no target keyword in its visible text).
_START_HTML = """
<title>IR</title>
<nav>
  <a href="/ir/dividend/">詳細はこちら</a>
  <a href="/recruit/">募集要項</a>
  <a href="https://ext.example.com/">外部リンク</a>
</nav>
"""
_DIVIDEND_HTML = (
    "<h1>配当方針</h1>"
    "<p>当社は安定配当を基本方針とし、配当性向30%を目安とします。"
    "営業キャッシュフローの範囲内で株主還元を行います。</p>"
)

_PAGES = {
    "https://www.mufg.jp/ir/": _START_HTML,
    "https://www.mufg.jp/ir/dividend/": _DIVIDEND_HTML,
}


def _policy(**overrides: object) -> CrawlPolicy:
    limits = overrides.pop("limits", CrawlLimits(max_depth=2, max_pages=10))
    return CrawlPolicy(
        allowed_domains=["www.mufg.jp"],
        url_prefix="https://www.mufg.jp/ir/",
        limits=limits,  # type: ignore[arg-type]
    )


def _make_fetch() -> tuple[list[str], object]:
    fetched: list[str] = []

    def fetch(url: str) -> FetchedPage:
        fetched.append(url)
        return FetchedPage(url=url, allowed=True, html=_PAGES.get(url, ""))

    return fetched, fetch


def test_crawl_reaches_dividend_page_and_skips_off_target() -> None:
    fetched, fetch = _make_fetch()
    report = crawl(_policy(), start_url="https://www.mufg.jp/ir/", fetch=fetch)  # type: ignore[arg-type]

    target_urls = [page.url for page in report.target_pages]
    assert "https://www.mufg.jp/ir/dividend/" in target_urls
    # The thin table-of-contents start page is not kept as a target page.
    assert "https://www.mufg.jp/ir/" not in target_urls
    # Off-target / external links are never fetched.
    assert "https://www.mufg.jp/recruit/" not in fetched
    assert "https://ext.example.com/" not in fetched
    assert fetched == ["https://www.mufg.jp/ir/", "https://www.mufg.jp/ir/dividend/"]


def test_crawl_stops_at_max_pages() -> None:
    fetched, fetch = _make_fetch()
    report = crawl(
        _policy(limits=CrawlLimits(max_depth=2, max_pages=1)),
        start_url="https://www.mufg.jp/ir/",
        fetch=fetch,  # type: ignore[arg-type]
    )
    assert report.fetched == 1
    assert report.stop_reason == "max_pages_reached"
    assert fetched == ["https://www.mufg.jp/ir/"]


def test_crawl_does_not_revisit_or_loop() -> None:
    # A page that links back to itself and to the start must not loop.
    pages = {
        "https://www.mufg.jp/ir/": '<a href="/ir/dividend/">配当 詳細</a>',
        "https://www.mufg.jp/ir/dividend/": (
            '<a href="/ir/dividend/">配当 自己ループ</a>'
            '<a href="/ir/">配当 戻る</a>'
            "<p>配当性向と株主還元の本文。</p>"
        ),
    }
    fetched: list[str] = []

    def fetch(url: str) -> FetchedPage:
        fetched.append(url)
        return FetchedPage(url=url, allowed=True, html=pages.get(url, ""))

    crawl(_policy(), start_url="https://www.mufg.jp/ir/", fetch=fetch)  # type: ignore[arg-type]

    assert sorted(fetched) == [
        "https://www.mufg.jp/ir/",
        "https://www.mufg.jp/ir/dividend/",
    ]


def test_crawl_records_blocked_fetch() -> None:
    def fetch(url: str) -> FetchedPage:
        return FetchedPage(url=url, allowed=False, html="")

    report = crawl(_policy(), start_url="https://www.mufg.jp/ir/", fetch=fetch)  # type: ignore[arg-type]
    assert report.target_pages == []
    assert report.skipped and report.skipped[0]["reason"] == "fetch_blocked_or_empty"


def test_crawl_surfaces_pdf_documents_and_skips_assets() -> None:
    # The TOC links to a dividend HTML page, a PDF 決算短信 (document), and a CSS
    # asset. Only the HTML page is fetched; the PDF is surfaced; the CSS dropped.
    pages = {
        "https://www.mufg.jp/ir/": (
            '<a href="/ir/dividend/">配当方針</a>'
            '<a href="/ir/kessan_tanshin.pdf">2024年3月期 決算短信</a>'
            '<a href="/ir/style.css">配当 stylesheet</a>'
        ),
        "https://www.mufg.jp/ir/dividend/": _DIVIDEND_HTML,
    }
    fetched: list[str] = []

    def fetch(url: str) -> FetchedPage:
        fetched.append(url)
        return FetchedPage(url=url, allowed=True, html=pages.get(url, ""))

    report = crawl(_policy(), start_url="https://www.mufg.jp/ir/", fetch=fetch)  # type: ignore[arg-type]

    # The CSS asset and the PDF are never fetched as HTML pages.
    assert "https://www.mufg.jp/ir/style.css" not in fetched
    assert "https://www.mufg.jp/ir/kessan_tanshin.pdf" not in fetched
    # The PDF is surfaced as a discovered document instead.
    doc_urls = [d["url"] for d in report.documents]
    assert "https://www.mufg.jp/ir/kessan_tanshin.pdf" in doc_urls
    assert report.documents[0]["anchor_text"] == "2024年3月期 決算短信"
    # The HTML dividend page is still crawled and kept.
    assert any(p.url == "https://www.mufg.jp/ir/dividend/" for p in report.target_pages)


def test_documents_surface_even_when_page_link_budget_is_full() -> None:
    # max_links_per_page=1: the high-scoring HTML page fills the page budget, but
    # a lower-ranked PDF must still be surfaced (recording is not page-budgeted).
    pages = {
        "https://www.mufg.jp/ir/": (
            '<a href="/ir/dividend/">配当方針 株主還元 配当性向</a>'
            '<a href="/ir/kessan_tanshin.pdf">決算短信</a>'
        ),
        "https://www.mufg.jp/ir/dividend/": _DIVIDEND_HTML,
    }

    def fetch(url: str) -> FetchedPage:
        return FetchedPage(url=url, allowed=True, html=pages.get(url, ""))

    report = crawl(
        _policy(),
        start_url="https://www.mufg.jp/ir/",
        fetch=fetch,  # type: ignore[arg-type]
        max_links_per_page=1,
    )

    # The single page-link slot is spent on the dividend page...
    assert "https://www.mufg.jp/ir/dividend/" in [p.url for p in report.target_pages]
    # ...yet the PDF is still surfaced (it would be dropped if the old top-of-loop
    # `added >= max_links_per_page` break still gated document recording).
    assert [d["url"] for d in report.documents] == [
        "https://www.mufg.jp/ir/kessan_tanshin.pdf"
    ]
