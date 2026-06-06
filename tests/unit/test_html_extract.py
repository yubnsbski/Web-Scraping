from __future__ import annotations

from investment_assistant.ingestion.html_extract import extract_text_from_html


def test_extract_text_from_html_removes_tags_scripts_and_styles() -> None:
    html = """
    <!doctype html>
    <html>
      <head>
        <title>Example &amp; Funds</title>
        <style>body { color: red; }</style>
        <script>console.log('hidden');</script>
      </head>
      <body>
        <h1>Fund Overview</h1>
        <p>Low cost &amp; globally diversified.</p>
        <noscript>hidden fallback</noscript>
      </body>
    </html>
    """

    text = extract_text_from_html(html)

    assert text == "Example & Funds\n\nFund Overview\nLow cost & globally diversified."
    assert "console" not in text
    assert "color" not in text
    assert "hidden fallback" not in text
    assert "<h1>" not in text


def test_extract_text_from_html_avoids_duplicate_title_when_heading_matches() -> None:
    html = (
        "<html><head><title>Same Title</title></head>"
        "<body><h1>Same Title</h1><p>Body</p></body></html>"
    )

    assert extract_text_from_html(html) == "Same Title\nBody"
