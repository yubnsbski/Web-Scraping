"""End-to-end data pipeline demo, fully offline (no network, no API keys).

Drives the *real* CLI paths with injected fakes so you can watch the whole
chain work without reaching EDINET or any IR site:

    IR crawl (fixture HTML)  -> RAG store -> search
    EDINET ingest (fake API) -> financials.csv
    financials.csv           -> dividend simulator + after-tax reverse calc

Run: python scripts/demo_offline_pipeline.py
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from investment_assistant import cli
from investment_assistant.crawler.frontier import FetchedPage
from investment_assistant.edinet.models import parse_documents
from investment_assistant.portfolio.simulator import (
    plan_for_target_dividend,
    simulate_portfolio,
)

# --- Stage 1 fixtures: a tiny IR site (table of contents -> dividend + PDF) ---

_IR_PAGES = {
    "https://demo.example.com/ir/": (
        '<a href="/ir/dividend/">配当方針・株主還元</a>'
        '<a href="/ir/kessan_tanshin.pdf">2024年3月期 決算短信</a>'
        '<a href="/ir/style.css">stylesheet</a>'
    ),
    "https://demo.example.com/ir/dividend/": (
        "<h1>配当方針</h1><p>当社は安定配当を基本方針とし、配当性向30%を目安に、"
        "営業キャッシュフローの範囲内で株主還元を行います。累進配当を志向します。</p>"
    ),
}


def _crawl_fetch(url: str) -> FetchedPage:
    return FetchedPage(url=url, allowed=True, html=_IR_PAGES.get(url, ""))


_IR_REGISTRY = """
sources:
  - name: "demo_ir_crawl"
    ticker: "0000"
    company: "デモ商事"
    source_type: "issuer_ir"
    method: "crawl"
    allowed: true
    url: "https://demo.example.com/ir/"
    allowed_domains: "demo.example.com"
    url_prefix: "https://demo.example.com/ir/"
    crawl_mode: "targeted"
    max_depth: 2
    max_pages: 10
"""


# --- Stage 2 fixtures: a fake EDINET API (canned doc list + CSV archives) -----


def _edinet_csv_zip(dps_current: str, dps_prior: str, equity: str) -> bytes:
    header = ("要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別",
              "期間・時点", "ユニットID", "単位", "値")
    div = "jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults"
    cells = [
        ("x:OCF", "営業活動によるキャッシュ・フロー", "CurrentYearDuration",
         "当期", "連結", "期間", "JPY", "百万円", "820000"),
        ("x:Eq", "自己資本比率", "CurrentYearInstant",
         "当期", "連結", "時点", "Pure", "％", equity),
        ("x:Po", "配当性向", "CurrentYearDuration",
         "当期", "連結", "期間", "Pure", "％", "31.2"),
        (div, "１株当たり配当額", "CurrentYearDuration",
         "当期", "連結", "期間", "JPY", "円", dps_current),
        (div, "１株当たり配当額", "Prior1YearDuration",
         "前期", "連結", "期間", "JPY", "円", dps_prior),
    ]
    lines = ["\t".join(header)] + ["\t".join(row) for row in cells]
    text = "\r\n".join(lines) + "\r\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("XBRL_TO_CSV/jpcrp.csv", text.encode("utf-16"))
    return buffer.getvalue()


def _edinet_doc(doc_id: str, period_end: str) -> dict[str, object]:
    return {
        "docID": doc_id,
        "secCode": "00000",
        "filerName": "デモ商事",
        "docTypeCode": "120",
        "docDescription": "有価証券報告書",
        "periodEnd": period_end,
        "submitDateTime": f"{period_end[:4]}-06-21 09:00",
        "csvFlag": "1",
    }


class _FakeEdinetClient:
    def __init__(self) -> None:
        self._docs = [_edinet_doc("S100DEMO", "2024-03-31")]
        self._archives = {"S100DEMO": _edinet_csv_zip("64", "58", "58.2")}

    def list_documents(self, date: str):  # type: ignore[no-untyped-def]
        # Return the canned filing only on its submission date.
        items = self._docs if date == "2024-06-21" else []
        return parse_documents({"results": items})

    def download_document(self, doc_id: str, *, acquisition_type: int = 5) -> bytes:
        return self._archives[doc_id]


_EDINET_REGISTRY = """
sources:
  - name: "demo_edinet"
    ticker: "0000"
    company: "デモ商事"
    source_type: "public_api"
    provider: "edinet"
    method: "api"
    allowed: true
    doc_types: "120"
"""


def _yen(value: object) -> str:
    return f"¥{int(float(str(value))):,}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rag_db = root / "rag.sqlite"
        ir_registry = root / "ir.yaml"
        ir_registry.write_text(_IR_REGISTRY, encoding="utf-8")
        edinet_registry = root / "edinet.yaml"
        edinet_registry.write_text(_EDINET_REGISTRY, encoding="utf-8")

        print("=" * 64)
        print("STAGE 1 — IR crawl (fixture HTML, fake fetch) -> RAG store")
        print("=" * 64)
        crawl_out = cli.run_crawl(
            path=ir_registry,
            output_dir=root / "crawl",
            db_path=rag_db,
            fetch=_crawl_fetch,
            index_after=True,
        )
        result = crawl_out["results"][0]  # type: ignore[index]
        print(f"  fetched pages : {result['fetched']}")
        print(f"  kept (target) : {result['target_pages_count']}")
        docs = result["documents"]  # type: ignore[index]
        print(f"  documents surfaced (not crawled as HTML): {[d['url'] for d in docs]}")
        print(f"  pages indexed : {crawl_out.get('index', {})}")

        print()
        print("=" * 64)
        print("STAGE 2 — RAG search over the crawled text")
        print("=" * 64)
        hits = cli.run_rag_search(query="配当性向 株主還元", db_path=rag_db, limit=1)
        if hits:
            print(f"  top hit source: {hits[0]['source']}")
            print(f"  excerpt       : {str(hits[0]['text'])[:70]}…")
        else:
            print("  (no hits)")

        print()
        print("=" * 64)
        print("STAGE 3 — EDINET ingest (fake API) -> financials.csv")
        print("=" * 64)
        ingest = cli.run_edinet_ingest(
            registry_path=edinet_registry,
            end_date="2024-06-21",
            days=1,
            output_dir=root / "edinet",
            client=_FakeEdinetClient(),  # type: ignore[arg-type]
            index_after=False,
        )
        csv_path = str(ingest["financials_csv"])
        data_rows = Path(csv_path).read_text(encoding="utf-8").strip().splitlines()[1:]
        print(f"  financials.csv: {csv_path}")
        print(f"  rows          : {data_rows}")

        print()
        print("=" * 64)
        print("STAGE 4 — Dividend simulator on the ingested data")
        print("=" * 64)
        holdings = [{"ticker": "0000", "price": 1800, "nisa": False}]
        sim = simulate_portfolio(
            budget=1_000_000, holdings=holdings, financials_csv=csv_path
        )
        summ = sim["summary"]  # type: ignore[index]
        print(f"  budget {_yen(summ['budget'])} -> invested {_yen(summ['invested'])}")
        print(f"  annual dividend {_yen(summ['annual_dividend'])} "
              f"(手取り {_yen(summ['annual_dividend_net'])})")

        plan = plan_for_target_dividend(
            target_annual_dividend=300_000,
            net_target=True,
            holdings=holdings,
            financials_csv=csv_path,
        )
        tgt = plan.get("target")
        if not tgt:
            print(f"  reverse calc: unavailable ({plan.get('reason', 'no data')})")
            print("\nOK — full pipeline ran offline (crawl + RAG + EDINET + simulator).")
            return 0
        reach = "reachable" if tgt["reachable"] else "unreachable"
        print(f"  reverse calc: 手取り {_yen(tgt['target_annual_dividend'])}/yr "
              f"-> 必要予算 {_yen(tgt['required_budget'])} ({reach})")

        print()
        print("OK — full pipeline ran offline (crawl + RAG + EDINET + simulator).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
