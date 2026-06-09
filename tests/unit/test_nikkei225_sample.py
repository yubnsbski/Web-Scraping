from __future__ import annotations

from pathlib import Path

from investment_assistant.cli import _fetch_job_sources
from investment_assistant.config.loader import load_yaml

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "nikkei225_sources_sample.yaml"

EXPECTED_CODES = ("9432", "2914", "8306")


def test_sample_job_parses_with_required_fields() -> None:
    config = load_yaml(SAMPLE)
    sources = _fetch_job_sources(config, SAMPLE)

    assert len(sources) == 3
    for source in sources:
        for field in ("name", "url", "output_path", "query_hint"):
            assert source.get(field), f"missing {field} in {source}"
        # Generated outputs must stay under the (uncommitted) sample directory.
        assert str(source["output_path"]).startswith("local_docs/nikkei225/")
        assert str(source["url"]).startswith("https://")
        assert source.get("extract_text") is True
        assert source.get("include_metadata") is True


def test_sample_job_covers_three_target_codes() -> None:
    config = load_yaml(SAMPLE)
    sources = _fetch_job_sources(config, SAMPLE)
    output_codes = {Path(str(source["output_path"])).parent.name for source in sources}
    assert output_codes == set(EXPECTED_CODES)
