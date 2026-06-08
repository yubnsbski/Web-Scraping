from __future__ import annotations

import io
import zipfile
from pathlib import Path

from investment_assistant.edinet.ingest import date_range, ingest_targets, recent_dates
from investment_assistant.edinet.registry import EdinetTarget


def _csv_zip(cf: str = "1234567", payout: str = "40.1", dps: str = "41.0") -> bytes:
    columns = [
        "要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別",
        "期間・時点", "ユニットID", "単位", "値",
    ]
    rows = [
        f"x:Cf\t営業活動によるキャッシュ・フロー\tCY\t当期\t連結\t期間\tJPY\t百万円\t{cf}",
        f"x:Po\t配当性向\tCY\t当期\t連結\t期間\tPure\t％\t{payout}",
        f"x:Dps\t１株当たり配当\tCY\t当期\t連結\t期間\tJPY\t円\t{dps}",
    ]
    text = "\r\n".join(["\t".join(columns), *rows]) + "\r\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("XBRL_TO_CSV/jpcrp.csv", text.encode("utf-16"))
    return buffer.getvalue()


class _FakeEdinetClient:
    """Returns canned document lists per date and a canned archive per doc id."""

    def __init__(
        self,
        documents_by_date: dict[str, list[dict[str, object]]],
        archives: dict[str, bytes] | None = None,
    ) -> None:
        self._documents_by_date = documents_by_date
        self._archives = archives or {}
        self.downloaded: list[str] = []

    def list_documents(self, date: str):  # type: ignore[no-untyped-def]
        from investment_assistant.edinet.models import parse_documents

        return parse_documents({"results": self._documents_by_date.get(date, [])})

    def download_document(self, doc_id: str, *, acquisition_type: int = 5) -> bytes:
        self.downloaded.append(doc_id)
        return self._archives.get(doc_id, _csv_zip())


def _mufg_doc(doc_id: str, submit: str) -> dict[str, object]:
    return {
        "docID": doc_id,
        "secCode": "83060",
        "filerName": "三菱UFJ",
        "docTypeCode": "120",
        "docDescription": "有価証券報告書",
        "periodEnd": "2024-03-31",
        "submitDateTime": submit,
        "csvFlag": "1",
    }


def test_recent_dates_returns_descending_span() -> None:
    assert recent_dates("2026-06-08", 3) == ["2026-06-08", "2026-06-07", "2026-06-06"]
    assert recent_dates("2026-06-08", 0) == ["2026-06-08"]


def test_date_range_skips_weekends_and_is_descending() -> None:
    # 2026-06-08 is Monday; 06-06 Sat and 06-07 Sun must be skipped.
    dates = date_range("2026-06-01", "2026-06-08")
    assert dates == [
        "2026-06-08",
        "2026-06-05",
        "2026-06-04",
        "2026-06-03",
        "2026-06-02",
        "2026-06-01",
    ]


def test_date_range_can_include_weekends() -> None:
    dates = date_range("2026-06-06", "2026-06-08", skip_weekends=False)
    assert dates == ["2026-06-08", "2026-06-07", "2026-06-06"]


def test_date_range_caps_at_max_days_keeping_recent() -> None:
    dates = date_range("2020-01-01", "2026-06-08", max_days=3)
    assert dates == ["2026-06-08", "2026-06-05", "2026-06-04"]


def test_date_range_handles_swapped_bounds() -> None:
    assert date_range("2026-06-08", "2026-06-01") == date_range("2026-06-01", "2026-06-08")


def test_run_edinet_ingest_backfill_years_scans_range(tmp_path: Path) -> None:
    from investment_assistant import cli

    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "sources:\n"
        '  - name: "8306"\n'
        '    ticker: "8306"\n'
        '    company: "MUFG"\n'
        '    source_type: "public_api"\n'
        '    provider: "edinet"\n'
        '    method: "api"\n'
        "    allowed: true\n",
        encoding="utf-8",
    )
    client = _FakeEdinetClient({"2026-06-08": [_mufg_doc("S100Y24", "2024-06-21 09:00")]})

    result = cli.run_edinet_ingest(
        registry_path=registry,
        end_date="2026-06-08",
        years=1,
        output_dir=tmp_path / "edinet",
        index_after=False,
        client=client,  # type: ignore[arg-type]
    )

    assert result["scan_mode"] == "backfill_1y"
    assert int(result["scanned_days_requested"]) > 200  # ~a year of business days
    assert result["ingested_count"] == 1


def test_ingest_targets_downloads_latest_and_writes_text(tmp_path: Path) -> None:
    client = _FakeEdinetClient(
        {
            "2026-06-08": [_mufg_doc("S100NEW", "2024-06-21 09:00")],
            "2026-06-07": [_mufg_doc("S100OLD", "2024-02-10 09:00")],
        }
    )
    target = EdinetTarget(name="8306_MUFG", ticker="8306", company="MUFG", doc_types=("120",))

    result = ingest_targets(
        client=client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08", "2026-06-07"],
        output_dir=tmp_path / "edinet",
    )

    assert result["ingested_count"] == 1
    # The most recent filing wins.
    assert client.downloaded == ["S100NEW"]
    saved = Path(tmp_path / "edinet" / "8306" / "S100NEW.txt")
    assert saved.is_file()
    body = saved.read_text(encoding="utf-8")
    assert "営業活動によるキャッシュ・フロー: 1234567" in body
    assert "配当性向: 40.1" in body


def _quarterly_doc(doc_id: str, submit: str, period_end: str) -> dict[str, object]:
    return {
        "docID": doc_id,
        "secCode": "83060",
        "filerName": "三菱UFJ",
        "docTypeCode": "140",
        "docDescription": "四半期報告書",
        "periodEnd": period_end,
        "submitDateTime": submit,
        "csvFlag": "1",
    }


def test_ingest_targets_keeps_multiple_periods(tmp_path: Path) -> None:
    client = _FakeEdinetClient(
        {
            "2026-06-08": [
                _mufg_doc("S100ANN", "2024-06-21 09:00"),
                _quarterly_doc("S100Q3", "2024-02-14 09:00", "2023-12-31"),
                _quarterly_doc("S100Q2", "2023-11-14 09:00", "2023-09-30"),
            ],
        }
    )
    target = EdinetTarget(
        name="8306_MUFG",
        ticker="8306",
        company="MUFG",
        doc_types=("120", "140"),
        max_periods=2,
    )

    result = ingest_targets(
        client=client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=tmp_path / "edinet",
    )

    # Two most-recent filings kept (annual + latest quarter), oldest dropped.
    assert result["ingested_count"] == 2
    assert client.downloaded == ["S100ANN", "S100Q3"]
    assert (tmp_path / "edinet" / "8306" / "S100ANN.txt").is_file()
    assert (tmp_path / "edinet" / "8306" / "S100Q3.txt").is_file()
    assert not (tmp_path / "edinet" / "8306" / "S100Q2.txt").exists()


def test_ingest_targets_skips_already_saved_documents(tmp_path: Path) -> None:
    documents = {"2026-06-08": [_mufg_doc("S100ANN", "2024-06-21 09:00")]}
    target = EdinetTarget(name="8306", ticker="8306", company="MUFG", doc_types=("120",))

    first_client = _FakeEdinetClient(documents)
    first = ingest_targets(
        client=first_client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=tmp_path / "edinet",
    )
    assert first["ingested_count"] == 1
    assert first_client.downloaded == ["S100ANN"]

    # Second run over the same output dir must not re-download.
    second_client = _FakeEdinetClient(documents)
    second = ingest_targets(
        client=second_client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=tmp_path / "edinet",
    )
    assert second["ingested_count"] == 0
    assert second["cached_count"] == 1
    assert second_client.downloaded == []


def test_ingest_builds_financials_csv_and_detects_dividend_cut(tmp_path: Path) -> None:
    # Two annual filings: FY2024 dividend lower than FY2023 -> a cut in 2024.
    client = _FakeEdinetClient(
        {
            "2026-06-08": [
                _mufg_doc("S100Y24", "2024-06-21 09:00"),  # period_end 2024-03-31
                {
                    "docID": "S100Y23",
                    "secCode": "83060",
                    "filerName": "三菱UFJ",
                    "docTypeCode": "120",
                    "docDescription": "有価証券報告書",
                    "periodEnd": "2023-03-31",
                    "submitDateTime": "2023-06-21 09:00",
                    "csvFlag": "1",
                },
            ],
        },
        archives={
            "S100Y24": _csv_zip(dps="40.0"),
            "S100Y23": _csv_zip(dps="50.0"),
        },
    )
    target = EdinetTarget(
        name="8306", ticker="8306", company="MUFG", doc_types=("120",), max_periods=2
    )

    result = ingest_targets(
        client=client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=tmp_path / "edinet",
    )

    assert result["financial_points"] == 2
    assert Path(str(result["financials_csv"])).is_file()
    comparison = result["comparison"]
    assert isinstance(comparison, dict)
    companies = comparison["companies"]
    assert isinstance(companies, list)
    mufg = companies[0]
    assert mufg["dividend_cut_years"] == [2024]
    assert mufg["dividend_trend"] == "declining"


def test_ingest_recovers_points_from_sidecar_on_cached_run(tmp_path: Path) -> None:
    documents = {"2026-06-08": [_mufg_doc("S100Y24", "2024-06-21 09:00")]}
    target = EdinetTarget(name="8306", ticker="8306", company="MUFG", doc_types=("120",))
    out_dir = tmp_path / "edinet"

    first = ingest_targets(
        client=_FakeEdinetClient(documents),  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=out_dir,
    )
    assert first["financial_points"] == 1

    # Second run: filing is cached, but its point is recovered from the sidecar.
    second_client = _FakeEdinetClient(documents)
    second = ingest_targets(
        client=second_client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=out_dir,
    )
    assert second["cached_count"] == 1
    assert second_client.downloaded == []
    assert second["financial_points"] == 1
    assert "comparison" in second


def test_ingest_targets_reports_missing_documents(tmp_path: Path) -> None:
    client = _FakeEdinetClient({})
    target = EdinetTarget(name="7203", ticker="7203", company="トヨタ", doc_types=("120",))

    result = ingest_targets(
        client=client,  # type: ignore[arg-type]
        targets=[target],
        dates=["2026-06-08"],
        output_dir=tmp_path / "edinet",
    )

    assert result["ingested_count"] == 0
    results = result["results"]
    assert isinstance(results, list)
    assert results[0]["status"] == "no_document"


def test_run_edinet_ingest_indexes_metrics_into_rag(tmp_path: Path) -> None:
    from investment_assistant import cli

    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "sources:\n"
        '  - name: "8306_MUFG_edinet"\n'
        '    ticker: "8306"\n'
        '    company: "MUFG"\n'
        '    source_type: "public_api"\n'
        '    provider: "edinet"\n'
        '    method: "api"\n'
        "    allowed: true\n",
        encoding="utf-8",
    )
    client = _FakeEdinetClient({"2026-06-08": [_mufg_doc("S100NEW", "2024-06-21 09:00")]})
    db_path = tmp_path / "rag.sqlite"

    result = cli.run_edinet_ingest(
        registry_path=registry,
        end_date="2026-06-08",
        days=1,
        output_dir=tmp_path / "edinet",
        db_path=db_path,
        client=client,  # type: ignore[arg-type]
    )

    assert result["ingested_count"] == 1
    assert "index" in result

    # The extracted numbers are now indexed and counted in the RAG store.
    stats = cli.run_rag_stats(db_path=db_path, keywords=("配当性向", "自己資本比率"))
    totals = stats["keyword_totals"]
    assert isinstance(totals, dict)
    assert totals["配当性向"] > 0
