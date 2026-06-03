from __future__ import annotations

from dataclasses import dataclass

from investment_assistant.llm.factory import build_llm_service, load_gemini_runtime_config


@dataclass
class FakeClient:
    calls: int = 0

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        return f"{model}:{prompt}"


def write_config(tmp_path):
    config_path = tmp_path / "gemini.yaml"
    usage_path = tmp_path / "usage.sqlite"
    cache_path = tmp_path / "cache.sqlite"
    config_path.write_text(
        f"""
gemini:
  enabled: true
  model: gemini-test
  daily_request_limit: 2
  monthly_request_limit: 10
  warning_threshold_ratio: 0.5
  hard_stop_threshold_ratio: 1.0
  usage_db_path: {usage_path}
  cache:
    enabled: true
    ttl_days: 7
    db_path: {cache_path}
  fallback:
    on_daily_limit: local_summary
    on_monthly_limit: skip_llm
    on_error: cached_or_skip
  allowed_tasks:
    - rag_answer
  blocked_tasks:
    - bulk_news_summary
""",
        encoding="utf-8",
    )
    return config_path


def test_load_gemini_runtime_config_normalizes_yaml(tmp_path):
    config_path = write_config(tmp_path)

    config = load_gemini_runtime_config(config_path)

    assert config.model == "gemini-test"
    assert config.cache_ttl_days == 7
    assert config.budget.daily_request_limit == 2
    assert config.budget.allowed_tasks == ("rag_answer",)
    assert config.budget.blocked_tasks == ("bulk_news_summary",)


def test_build_llm_service_from_config_uses_injected_client_and_cache(tmp_path):
    config_path = write_config(tmp_path)
    client = FakeClient()
    service = build_llm_service(config_path, client=client)

    first = service.generate(task_type="rag_answer", prompt="hello")
    second = service.generate(task_type="rag_answer", prompt="hello")

    assert first.text == "gemini-test:hello"
    assert first.source == "gemini"
    assert second.source == "cache"
    assert client.calls == 1
