from __future__ import annotations

from investment_assistant.config.loader import load_yaml


def test_load_yaml_supports_list_of_mappings(tmp_path):
    path = tmp_path / "fetch_job.yaml"
    path.write_text(
        """
sources:
  - name: example
    url: https://example.com/
    output_path: local_docs/example.txt
    extract_text: true
    preview_chars: 300
  - name: docs
    url: https://example.com/docs
    output_path: local_docs/docs.txt
allowed_tasks:
  - rag_answer
""",
        encoding="utf-8",
    )

    config = load_yaml(path)

    sources = config["sources"]
    assert isinstance(sources, list)
    assert sources[0]["name"] == "example"
    assert sources[0]["extract_text"] is True
    assert sources[0]["preview_chars"] == 300
    assert sources[1]["output_path"] == "local_docs/docs.txt"
    assert config["allowed_tasks"] == ["rag_answer"]
