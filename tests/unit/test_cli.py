from __future__ import annotations

import json

from investment_assistant.cli import build_budget_report, main, run_smoke


def write_config(tmp_path):
    config_path = tmp_path / "gemini.yaml"
    config_path.write_text(
        f"""
gemini:
  enabled: true
  model: gemini-test
  daily_request_limit: 5
  monthly_request_limit: 20
  warning_threshold_ratio: 0.8
  hard_stop_threshold_ratio: 1.0
  usage_db_path: {tmp_path / "usage.sqlite"}
  cache:
    enabled: true
    ttl_days: 30
    db_path: {tmp_path / "cache.sqlite"}
  fallback:
    on_daily_limit: local_summary
    on_monthly_limit: skip_llm
    on_error: cached_or_skip
  allowed_tasks:
    - rag_answer
  blocked_tasks: []
""",
        encoding="utf-8",
    )
    return config_path


def test_build_budget_report_does_not_call_gemini(tmp_path):
    config_path = write_config(tmp_path)

    report = build_budget_report(config_path)

    assert report.model == "gemini-test"
    assert report.daily_used == 0
    assert report.daily_remaining == 5


def test_run_smoke_uses_guarded_service_with_echo_client(tmp_path):
    config_path = write_config(tmp_path)

    result = run_smoke(config_path=config_path, prompt="hello")

    assert result["text"] == "[smoke:gemini-test] hello"
    assert result["source"] == "gemini"
    assert result["skipped"] is False


def test_cli_budget_json_outputs_report(tmp_path, capsys):
    config_path = write_config(tmp_path)

    exit_code = main(["--config", str(config_path), "budget", "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["model"] == "gemini-test"
    assert output["daily_used"] == 0


def test_cli_smoke_outputs_json(tmp_path, capsys):
    config_path = write_config(tmp_path)

    exit_code = main(["--config", str(config_path), "smoke", "--prompt", "hello"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["text"] == "[smoke:gemini-test] hello"


def test_cli_gemini_live_requires_explicit_acknowledgement(tmp_path, capsys):
    config_path = write_config(tmp_path)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "gemini-live",
            "--prompt",
            "hello",
        ]
    )

    assert exit_code == 2
    assert "--call-real-api" in capsys.readouterr().out


def test_cli_fetch_url_dry_run_outputs_json(monkeypatch, capsys):
    class FakeFetcher:
        def fetch(
            self,
            url: str,
            *,
            dry_run: bool,
            preview_chars: int,
            save_text: str | None = None,
            extract_text: bool = False,
            include_metadata: bool = False,
        ):
            from investment_assistant.ingestion.fetcher import FetchResult

            assert url == "https://example.com/funds"
            assert dry_run is True
            assert preview_chars == 120
            assert save_text is None
            assert extract_text is False
            assert include_metadata is False
            return FetchResult(
                url=url,
                status_code=None,
                source="dry_run",
                allowed_by_robots=True,
                robots_url="https://example.com/robots.txt",
                bytes_read=0,
                content_type=None,
                text_preview=None,
                dry_run=True,
            )

    monkeypatch.setattr("investment_assistant.cli.SafeFetcher", FakeFetcher)

    exit_code = main(
        [
            "fetch-url",
            "--url",
            "https://example.com/funds",
            "--dry-run",
            "--preview-chars",
            "120",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "dry_run"
    assert output["allowed_by_robots"] is True


def test_cli_fetch_url_save_text_passes_output_path(monkeypatch, tmp_path, capsys):
    save_path = tmp_path / "saved" / "page.txt"

    class FakeFetcher:
        def fetch(
            self,
            url: str,
            *,
            dry_run: bool,
            preview_chars: int,
            save_text: str | None = None,
            extract_text: bool = False,
            include_metadata: bool = False,
        ):
            from investment_assistant.ingestion.fetcher import FetchResult

            assert url == "https://example.com/funds"
            assert dry_run is False
            assert preview_chars == 200
            assert save_text == str(save_path)
            assert extract_text is False
            assert include_metadata is False
            return FetchResult(
                url=url,
                status_code=200,
                source="network",
                allowed_by_robots=True,
                robots_url="https://example.com/robots.txt",
                bytes_read=9,
                content_type="text/plain; charset=utf-8",
                text_preview="fund data",
                dry_run=False,
                saved_path=str(save_path),
            )

    monkeypatch.setattr("investment_assistant.cli.SafeFetcher", FakeFetcher)

    exit_code = main(
        [
            "fetch-url",
            "--url",
            "https://example.com/funds",
            "--preview-chars",
            "200",
            "--save-text",
            str(save_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "network"
    assert output["saved_path"] == str(save_path)


def test_cli_fetch_url_extract_text_and_metadata_pass_flags(monkeypatch, tmp_path, capsys):
    save_path = tmp_path / "saved" / "page.txt"

    class FakeFetcher:
        def fetch(
            self,
            url: str,
            *,
            dry_run: bool,
            preview_chars: int,
            save_text: str | None = None,
            extract_text: bool = False,
            include_metadata: bool = False,
        ):
            from investment_assistant.ingestion.fetcher import FetchResult

            assert url == "https://example.com/funds"
            assert dry_run is False
            assert preview_chars == 200
            assert save_text == str(save_path)
            assert extract_text is True
            assert include_metadata is True
            return FetchResult(
                url=url,
                status_code=200,
                source="network",
                allowed_by_robots=True,
                robots_url="https://example.com/robots.txt",
                bytes_read=42,
                content_type="text/html; charset=utf-8",
                text_preview="Fund data",
                dry_run=False,
                saved_path=str(save_path),
                extracted_text=True,
                metadata_included=True,
            )

    monkeypatch.setattr("investment_assistant.cli.SafeFetcher", FakeFetcher)

    exit_code = main(
        [
            "fetch-url",
            "--url",
            "https://example.com/funds",
            "--preview-chars",
            "200",
            "--extract-text",
            "--include-metadata",
            "--save-text",
            str(save_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "network"
    assert output["saved_path"] == str(save_path)
    assert output["extracted_text"] is True
    assert output["metadata_included"] is True


def test_cli_fetch_job_runs_yaml_sources(monkeypatch, tmp_path, capsys):
    job_path = tmp_path / "fetch_job.yaml"
    first_output = tmp_path / "local_docs" / "example.txt"
    second_output = tmp_path / "local_docs" / "docs.txt"
    job_path.write_text(
        f"""
sources:
  - name: example
    url: https://example.com/
    output_path: {first_output}
    query_hint: Example Domain
    extract_text: true
    preview_chars: 123
  - name: docs
    url: https://example.com/docs
    output_path: {second_output}
    extract_text: false
""",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    class FakeFetcher:
        def fetch(
            self,
            url: str,
            *,
            dry_run: bool,
            preview_chars: int,
            save_text: str | None = None,
            extract_text: bool = False,
            include_metadata: bool = False,
        ):
            from investment_assistant.ingestion.fetcher import FetchResult

            calls.append({
                "url": url,
                "dry_run": dry_run,
                "preview_chars": preview_chars,
                "save_text": save_text,
                "extract_text": extract_text,
                "include_metadata": include_metadata,
            })
            return FetchResult(
                url=url,
                status_code=200,
                source="network",
                allowed_by_robots=True,
                robots_url="https://example.com/robots.txt",
                bytes_read=12,
                content_type="text/html",
                text_preview="Example",
                dry_run=dry_run,
                saved_path=save_text,
                extracted_text=extract_text,
                metadata_included=include_metadata and save_text is not None,
            )

    monkeypatch.setattr("investment_assistant.cli.SafeFetcher", FakeFetcher)

    exit_code = main(["fetch-job", "--path", str(job_path), "--preview-chars", "500"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["sources_count"] == 2
    assert output["results"][0]["name"] == "example"
    assert output["results"][0]["query_hint"] == "Example Domain"
    assert output["results"][0]["fetch"]["saved_path"] == str(first_output)
    assert calls == [
        {
            "url": "https://example.com/",
            "dry_run": False,
            "preview_chars": 123,
            "save_text": str(first_output),
            "extract_text": True,
            "include_metadata": True,
        },
        {
            "url": "https://example.com/docs",
            "dry_run": False,
            "preview_chars": 500,
            "save_text": str(second_output),
            "extract_text": False,
            "include_metadata": True,
        },
    ]


def test_cli_fetch_job_dry_run_does_not_save(monkeypatch, tmp_path, capsys):
    job_path = tmp_path / "fetch_job.yaml"
    output_path = tmp_path / "local_docs" / "example.txt"
    job_path.write_text(
        f"""
sources:
  - name: example
    url: https://example.com/
    output_path: {output_path}
""",
        encoding="utf-8",
    )

    class FakeFetcher:
        def fetch(
            self,
            url: str,
            *,
            dry_run: bool,
            preview_chars: int,
            save_text: str | None = None,
            extract_text: bool = False,
            include_metadata: bool = False,
        ):
            from investment_assistant.ingestion.fetcher import FetchResult

            assert dry_run is True
            assert save_text is None
            assert extract_text is True
            assert include_metadata is True
            return FetchResult(
                url=url,
                status_code=None,
                source="dry_run",
                allowed_by_robots=True,
                robots_url="https://example.com/robots.txt",
                bytes_read=0,
                content_type=None,
                text_preview=None,
                dry_run=True,
            )

    monkeypatch.setattr("investment_assistant.cli.SafeFetcher", FakeFetcher)

    exit_code = main(["fetch-job", "--path", str(job_path), "--dry-run"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["results"][0]["fetch"]["saved_path"] is None


def test_cli_rag_index_search_and_context(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    doc_path = tmp_path / "memo.md"
    doc_path.write_text(
        "投資判断はユーザーが行います。\n自動売買は行いません。",
        encoding="utf-8",
    )

    index_exit = main(
        [
            "rag-index",
            "--path",
            str(doc_path),
            "--db-path",
            str(db_path),
        ]
    )
    assert index_exit == 0
    index_output = json.loads(capsys.readouterr().out)
    assert index_output["chunks_indexed"] == 1

    search_exit = main(
        [
            "rag-search",
            "--query",
            "投資判断",
            "--db-path",
            str(db_path),
        ]
    )
    assert search_exit == 0
    search_output = json.loads(capsys.readouterr().out)
    assert search_output[0]["source"] == str(doc_path)

    context_exit = main(
        [
            "rag-answer-context",
            "--query",
            "自動売買",
            "--db-path",
            str(db_path),
        ]
    )
    assert context_exit == 0
    context_output = json.loads(capsys.readouterr().out)
    assert "自動売買" in context_output["context"]


def test_cli_rag_index_dir_indexes_supported_files(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    nested_dir = docs_dir / "nested"
    nested_dir.mkdir(parents=True)
    (docs_dir / "memo.txt").write_text("投資判断はユーザーが行います。", encoding="utf-8")
    (nested_dir / "note.md").write_text("自動売買は行いません。", encoding="utf-8")
    (docs_dir / "ignored.csv").write_text("name,value\nA,1\n", encoding="utf-8")

    index_exit = main(
        [
            "rag-index-dir",
            "--path",
            str(docs_dir),
            "--db-path",
            str(db_path),
            "--max-chars",
            "80",
            "--overlap-chars",
            "0",
        ]
    )
    assert index_exit == 0
    index_output = json.loads(capsys.readouterr().out)
    assert index_output["files_indexed"] == 2
    assert index_output["chunks_indexed"] == 2
    assert str(docs_dir / "ignored.csv") in index_output["skipped_files"]

    search_exit = main(
        [
            "rag-search",
            "--query",
            "投資判断",
            "--db-path",
            str(db_path),
        ]
    )
    assert search_exit == 0
    search_output = json.loads(capsys.readouterr().out)
    assert search_output[0]["source"] == str(docs_dir / "memo.txt")


def test_cli_scoring_rank_outputs_guarded_report(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
        "高コストテーマ型,1.20,0.080,0.35,0.45\n"
        "債券バランス型,0.35,0.030,0.08,0.80\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scoring-rank",
            "--path",
            str(csv_path),
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["call_real_api"] is False
    assert output["auto_trading"] is False
    assert len(output["results"]) == 2
    assert output["results"][0]["name"] == "低コスト全世界株式"
    assert "投資助言" in output["disclaimer"]


def _write_funds_csv(path) -> None:
    path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
        "高コストテーマ型,1.20,0.080,0.35,0.45\n"
        "債券バランス型,0.35,0.030,0.08,0.80\n",
        encoding="utf-8",
    )


def test_cli_scoring_rank_writes_output_file(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    output_path = tmp_path / "reports" / "ranking.json"
    _write_funds_csv(csv_path)

    exit_code = main(
        ["scoring-rank", "--path", str(csv_path), "--limit", "2", "--output", str(output_path)]
    )

    assert exit_code == 0
    assert output_path.exists()
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["source"] == str(csv_path)
    assert saved["count"] == 3
    assert len(saved["results"]) == 2
    assert saved["call_real_api"] is False
    assert saved["auto_trading"] is False
    summary = json.loads(capsys.readouterr().out)
    assert summary["output"] == str(output_path)
    assert summary["count"] == 3


def test_cli_scoring_rank_refuses_overwrite_without_flag(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    output_path = tmp_path / "ranking.json"
    _write_funds_csv(csv_path)
    output_path.write_text("existing", encoding="utf-8")

    exit_code = main(
        ["scoring-rank", "--path", str(csv_path), "--output", str(output_path)]
    )
    assert exit_code == 1
    assert output_path.read_text(encoding="utf-8") == "existing"  # not overwritten
    assert "already exists" in capsys.readouterr().out

    exit_code = main(
        ["scoring-rank", "--path", str(csv_path), "--output", str(output_path), "--overwrite"]
    )
    assert exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["count"] == 3


def test_cli_scoring_rank_table_format(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    _write_funds_csv(csv_path)
    exit_code = main(["scoring-rank", "--path", str(csv_path), "--limit", "3", "--format", "table"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "rank | name" in out
    assert "低コスト全世界株式" in out
    assert "投資助言" in out


def test_cli_scoring_validate_outputs_valid_json(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
        "高コストテーマ型,1.20,0.080,0.35,0.45\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scoring-validate",
            "--path",
            str(csv_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["rows"] == 2
    assert output["warnings"] == []
    assert output["call_real_api"] is False
    assert output["auto_trading"] is False


def test_cli_scoring_validate_outputs_errors_for_invalid_csv(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        ",0.12,0.065,0.18,0.95\n"
        "BadDiversification,0.1,0.05,0.2,1.2\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scoring-validate",
            "--path",
            str(csv_path),
        ]
    )

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is False
    assert output["rows"] == 2
    assert len(output["errors"]) == 2
    assert any("name is required" in error for error in output["errors"])
    assert any(
        "diversification_score must be between 0 and 1" in error for error in output["errors"]
    )


def test_cli_rag_search_table_outputs_metadata(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    doc_path = tmp_path / "fetched.txt"
    doc_path.write_text(
        "---\n"
        'source_url: "https://example.com/funds"\n'
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "status_code: 200\n"
        'content_type: "text/html; charset=utf-8"\n'
        "extracted_text: true\n"
        "---\n\n"
        "Fund Page\n\nVisible text for 投資判断 and metadata table output.",
        encoding="utf-8",
    )

    index_exit = main(
        [
            "rag-index",
            "--path",
            str(doc_path),
            "--db-path",
            str(db_path),
            "--max-chars",
            "120",
            "--overlap-chars",
            "0",
        ]
    )
    assert index_exit == 0
    capsys.readouterr()

    search_exit = main(
        [
            "rag-search",
            "--query",
            "投資判断",
            "--db-path",
            str(db_path),
            "--limit",
            "1",
            "--format",
            "table",
            "--text-preview-chars",
            "40",
        ]
    )

    assert search_exit == 0
    output = capsys.readouterr().out
    assert "| rank | score | source | chunk | metadata | text_preview |" in output
    assert "source_url=https://example.com/funds" in output
    assert "fetched_at=2026-06-06T00:00:00Z" in output
    assert "status_code=200" in output
    assert "content_type=text/html; charset=utf-8" in output
    assert "Visible text for 投資判断" in output
    assert "source_url:" not in output


def test_cli_rag_search_table_columns_customizes_output(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    doc_path = tmp_path / "fetched.txt"
    doc_path.write_text(
        "---\n"
        'source_url: "https://example.com/funds"\n'
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "status_code: 200\n"
        'content_type: "text/html; charset=utf-8"\n'
        "---\n\n"
        "Fund Page for 投資判断.",
        encoding="utf-8",
    )

    assert main(["rag-index", "--path", str(doc_path), "--db-path", str(db_path)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search",
            "--query",
            "投資判断",
            "--db-path",
            str(db_path),
            "--format",
            "table",
            "--columns",
            "rank,source_url,fetched_at,text_preview",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "| rank | source_url | fetched_at | text_preview |" in output
    assert "https://example.com/funds" in output
    assert "2026-06-06T00:00:00Z" in output
    assert "Fund Page for 投資判断." in output
    assert "| score |" not in output
    assert "metadata" not in output


def test_cli_rag_search_job_uses_query_hint_and_name_fallback(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    docs_dir.mkdir()
    first_doc = docs_dir / "example.txt"
    second_doc = docs_dir / "fallback.txt"
    first_doc.write_text(
        "---\n"
        'source_url: "https://example.com/"\n'
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "status_code: 200\n"
        "---\n\n"
        "Example Domain の説明です。",
        encoding="utf-8",
    )
    second_doc.write_text("fallback source の説明です。", encoding="utf-8")
    job_path = tmp_path / "fetch_job.yaml"
    job_path.write_text(
        f"""
sources:
  - name: example
    url: https://example.com/
    output_path: {first_doc}
    query_hint: Example Domain
  - name: fallback
    url: https://example.com/fallback
    output_path: {second_doc}
""",
        encoding="utf-8",
    )

    assert main(["rag-index-dir", "--path", str(docs_dir), "--db-path", str(db_path)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search-job",
            "--path",
            str(job_path),
            "--db-path",
            str(db_path),
            "--limit",
            "1",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["sources_count"] == 2
    assert output["results"][0]["query"] == "Example Domain"
    assert output["results"][0]["results"][0]["metadata"]["source_url"] == "https://example.com/"
    assert output["results"][1]["query"] == "fallback"
    assert output["results"][1]["results"][0]["source"] == str(second_doc)


def test_cli_rag_search_job_table_reuses_search_table_formatter(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    docs_dir.mkdir()
    doc_path = docs_dir / "example.txt"
    doc_path.write_text(
        "---\n"
        'source_url: "https://example.com/"\n'
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "---\n\n"
        "Example Domain table output.",
        encoding="utf-8",
    )
    job_path = tmp_path / "fetch_job.yaml"
    job_path.write_text(
        f"""
sources:
  - name: example
    url: https://example.com/
    output_path: {doc_path}
    query_hint: Example Domain
""",
        encoding="utf-8",
    )

    assert main(["rag-index-dir", "--path", str(docs_dir), "--db-path", str(db_path)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search-job",
            "--path",
            str(job_path),
            "--db-path",
            str(db_path),
            "--format",
            "table",
            "--columns",
            "rank,source_url,fetched_at,text_preview",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "## example | query=Example Domain | url=https://example.com/" in output
    assert "| rank | source_url | fetched_at | text_preview |" in output
    assert "https://example.com/" in output
    assert "2026-06-06T00:00:00Z" in output
    assert "Example Domain table output." in output


def test_cli_rag_search_job_save_report_writes_markdown_table(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    report_path = tmp_path / "local_reports" / "rag_search_job.md"
    docs_dir.mkdir()
    doc_path = docs_dir / "example.txt"
    doc_path.write_text(
        "---\n"
        'source_url: "https://example.com/"\n'
        "fetched_at: 2026-06-06T00:00:00Z\n"
        "---\n\n"
        "Example Domain markdown report.",
        encoding="utf-8",
    )
    job_path = tmp_path / "fetch_job.yaml"
    job_path.write_text(
        f"""
sources:
  - name: example
    url: https://example.com/
    output_path: {doc_path}
    query_hint: Example Domain
""",
        encoding="utf-8",
    )

    assert main(["rag-index-dir", "--path", str(docs_dir), "--db-path", str(db_path)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search-job",
            "--path",
            str(job_path),
            "--db-path",
            str(db_path),
            "--format",
            "table",
            "--columns",
            "rank,source_url,fetched_at,text_preview",
            "--save-report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    saved = report_path.read_text(encoding="utf-8")
    assert f"saved_report_path: {report_path}" in output
    assert report_path.parent.is_dir()
    assert "## example | query=Example Domain | url=https://example.com/" in saved
    assert "| rank | source_url | fetched_at | text_preview |" in saved
    assert "Example Domain markdown report." in saved


def test_cli_rag_search_job_save_report_writes_json(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    report_path = tmp_path / "local_reports" / "rag_search_job.json"
    docs_dir.mkdir()
    doc_path = docs_dir / "example.txt"
    doc_path.write_text("Example Domain json report.", encoding="utf-8")
    job_path = tmp_path / "fetch_job.yaml"
    job_path.write_text(
        f"""
sources:
  - name: example
    url: https://example.com/
    output_path: {doc_path}
    query_hint: Example Domain
""",
        encoding="utf-8",
    )

    assert main(["rag-index-dir", "--path", str(docs_dir), "--db-path", str(db_path)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search-job",
            "--path",
            str(job_path),
            "--db-path",
            str(db_path),
            "--format",
            "json",
            "--save-report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert output["saved_report_path"] == str(report_path)
    assert saved["saved_report_path"] == str(report_path)
    assert saved["results"][0]["query"] == "Example Domain"
    assert saved["results"][0]["results"][0]["text"] == "Example Domain json report."



def test_cli_rag_search_job_scope_job_source_filters_results(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    docs_dir.mkdir()

    first_doc = docs_dir / "first.txt"
    second_doc = docs_dir / "second.txt"

    first_doc.write_text("alpha company 配当 方針 unique-first", encoding="utf-8")
    second_doc.write_text("beta company 配当 方針 unique-second", encoding="utf-8")

    job_path = tmp_path / "fetch_job.yaml"
    job_path.write_text(
        f"""
sources:
  - name: first
    url: https://example.com/first
    output_path: {first_doc}
    query_hint: 配当 方針
  - name: second
    url: https://example.com/second
    output_path: {second_doc}
    query_hint: 配当 方針
""",
        encoding="utf-8",
    )

    assert main(
        ["rag-index-dir", "--path", str(docs_dir), "--db-path", str(db_path)]
    ) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search-job",
            "--path",
            str(job_path),
            "--db-path",
            str(db_path),
            "--limit",
            "5",
            "--scope",
            "job-source",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)

    first_results = output["results"][0]["results"]
    second_results = output["results"][1]["results"]

    assert first_results
    assert second_results
    assert {row["source"] for row in first_results} == {str(first_doc)}
    assert {row["source"] for row in second_results} == {str(second_doc)}


def test_cli_rag_search_job_scope_job_source_filters_saved_table(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    docs_dir = tmp_path / "local_docs"
    report_path = tmp_path / "reports" / "scoped.md"
    docs_dir.mkdir()

    first_doc = docs_dir / "first.txt"
    second_doc = docs_dir / "second.txt"

    first_doc.write_text("alpha company 配当 方針 unique-first", encoding="utf-8")
    second_doc.write_text("beta company 配当 方針 unique-second", encoding="utf-8")

    job_path = tmp_path / "fetch_job.yaml"
    job_path.write_text(
        f"""
sources:
  - name: first
    url: https://example.com/first
    output_path: {first_doc}
    query_hint: 配当 方針
  - name: second
    url: https://example.com/second
    output_path: {second_doc}
    query_hint: 配当 方針
""",
        encoding="utf-8",
    )

    assert main(
        ["rag-index-dir", "--path", str(docs_dir), "--db-path", str(db_path)]
    ) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "rag-search-job",
            "--path",
            str(job_path),
            "--db-path",
            str(db_path),
            "--format",
            "table",
            "--columns",
            "rank,source,text_preview",
            "--save-report",
            str(report_path),
            "--scope",
            "job-source",
        ]
    )

    assert exit_code == 0
    assert f"saved_report_path: {report_path}" in capsys.readouterr().out

    saved = report_path.read_text(encoding="utf-8")
    first_block = saved.split("## second", 1)[0]
    second_block = saved.split("## second", 1)[1]

    assert str(first_doc) in first_block
    assert str(second_doc) not in first_block
    assert str(second_doc) in second_block
    assert str(first_doc) not in second_block
