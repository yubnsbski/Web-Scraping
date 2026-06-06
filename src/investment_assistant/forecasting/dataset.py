"""Acquire real financial time-series data for forecasting.

Data is downloaded with the SSRF-validating, size-limited HTTP transport used
elsewhere in the project. Because this is a direct download of an explicitly
chosen data file (not crawling), and because the data hosts here do not serve a
normal ``robots.txt``, acquisition is restricted to an allowlist of trusted data
hosts rather than going through the crawler robots check.

The default dataset is Robert Shiller's long-run S&P 500 series (monthly price,
dividend, earnings, CPI, long interest rate, PE10) mirrored by the ``datasets``
project on GitHub -- genuine financial data with a permissive license.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from investment_assistant.ingestion.fetcher import reject_path_traversal
from investment_assistant.ingestion.transport import (
    HttpTransport,
    UrlLibHttpTransport,
    validate_public_http_url,
)

ALLOWED_DATA_HOSTS = frozenset({"raw.githubusercontent.com"})

KNOWN_DATASETS: dict[str, str] = {
    "sp500_shiller": (
        "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"
    ),
}

DEFAULT_DATASET = "sp500_shiller"
DEFAULT_USER_AGENT = "investment-assistant-forecasting/0.1 (+research; no-auto-trading)"


def resolve_dataset_url(name_or_url: str) -> str:
    """Map a known dataset name to its URL, or pass through an explicit URL."""

    return KNOWN_DATASETS.get(name_or_url, name_or_url)


def download_dataset(
    name_or_url: str = DEFAULT_DATASET,
    *,
    dest: str | Path,
    transport: HttpTransport | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, object]:
    """Download a financial dataset CSV to ``dest`` and return a summary."""

    url = resolve_dataset_url(name_or_url)
    validate_public_http_url(url)
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_DATA_HOSTS:
        msg = (
            f"Refusing to download from untrusted host {host!r}. "
            f"Allowed data hosts: {sorted(ALLOWED_DATA_HOSTS)}"
        )
        raise ValueError(msg)

    dest_path = reject_path_traversal(dest)
    client = transport or UrlLibHttpTransport()
    response = client.get(url, timeout_seconds=timeout_seconds, user_agent=DEFAULT_USER_AGENT)
    if response.status_code >= 400:
        msg = f"Download failed with HTTP {response.status_code}: {url}"
        raise OSError(msg)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(response.body)
    line_count = response.body.count(b"\n")
    return {
        "dataset": name_or_url,
        "url": url,
        "dest": str(dest_path),
        "bytes": len(response.body),
        "approx_rows": max(0, line_count - 1),
    }
