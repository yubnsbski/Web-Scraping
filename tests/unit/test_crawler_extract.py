from __future__ import annotations

from investment_assistant.crawler.extract import (
    assess_page,
    extract_links,
    rank_links,
    score_link,
)

_IR_TOC_HTML = """
<!doctype html>
<html><head><title>IR（投資家情報）</title></head>
<body>
  <nav>
    <a href="/ir/dividend/">配当方針・株主還元</a>
    <a href="https://www.mufg.jp/ir/financial/highlight.html">財務ハイライト・決算</a>
    <a href="/recruit/">採用情報</a>
    <a href="news/2026/index.html">ニュース一覧</a>
    <a href="/ir/dividend/#policy">配当（同じページ）</a>
    <a href="mailto:ir@example.com">お問い合わせ</a>
  </nav>
</body></html>
"""


def test_extract_links_resolves_relative_and_drops_fragment_duplicates() -> None:
    links = extract_links(_IR_TOC_HTML, base_url="https://www.mufg.jp/ir/")
    urls = [link.url for link in links]

    # Relative path resolved against the base URL.
    assert "https://www.mufg.jp/ir/dividend/" in urls
    # Absolute URL kept as-is.
    assert "https://www.mufg.jp/ir/financial/highlight.html" in urls
    # Relative path without leading slash resolved against the directory.
    assert "https://www.mufg.jp/ir/news/2026/index.html" in urls
    # Non-http(s) scheme dropped.
    assert all(not url.startswith("mailto:") for url in urls)
    # The #policy fragment duplicate collapses into the bare dividend URL.
    assert urls.count("https://www.mufg.jp/ir/dividend/") == 1


def test_dividend_link_scores_high_and_recruit_scores_negative() -> None:
    links = extract_links(_IR_TOC_HTML, base_url="https://www.mufg.jp/ir/")
    by_url = {link.url: score_link(link) for link in links}

    dividend = by_url["https://www.mufg.jp/ir/dividend/"]
    recruit = by_url["https://www.mufg.jp/recruit/"]

    assert dividend.score > 0
    assert "配当" in dividend.matched_targets
    assert recruit.score < 0
    assert "採用" in recruit.matched_excludes
    assert dividend.score > recruit.score


def test_rank_links_orders_targets_before_excluded() -> None:
    links = extract_links(_IR_TOC_HTML, base_url="https://www.mufg.jp/ir/")
    ranked = rank_links(links)

    assert ranked[0].score >= ranked[-1].score
    top_url = ranked[0].url
    assert top_url in {
        "https://www.mufg.jp/ir/dividend/",
        "https://www.mufg.jp/ir/financial/highlight.html",
    }
    # The recruit link must not rank at the top.
    assert ranked[0].url != "https://www.mufg.jp/recruit/"


def test_assess_page_rejects_short_toc_without_keywords() -> None:
    # Mirrors today's edinet_portal.txt (172 chars) — thin and off-target.
    thin = "EDINET 書類検索 トップ メニュー ログイン 利用規約 " * 6
    assert len(thin.strip()) < 800
    verdict = assess_page(thin)
    assert not verdict.is_substantive
    assert verdict.reason == "thin_page"


def test_assess_page_rejects_690_char_index_with_zero_hits() -> None:
    # Mirrors the Toyota table-of-contents page: ~690 chars, zero target hits.
    toc = "あ" * 690
    verdict = assess_page(toc)
    assert verdict.char_count == 690
    assert verdict.keyword_hits == 0
    assert not verdict.is_substantive


def test_assess_page_accepts_long_body() -> None:
    body = "当社の配当方針について説明します。" + ("本文" * 500)
    verdict = assess_page(body)
    assert verdict.is_substantive
    assert verdict.reason == "enough_text"


def test_assess_page_accepts_short_body_with_target_keyword() -> None:
    # Short, but carries a target keyword, so it is not quarantined.
    body = "配当性向は40%を目安とします。"
    verdict = assess_page(body)
    assert verdict.is_substantive
    assert verdict.reason == "keyword_match"
    assert verdict.keyword_hits >= 1
