"""Unit tests for ``POST /api/vtrade/advice`` (仮想取引 × AIアドバイザー).

Same synthetic-CSV + :func:`configure` pattern as ``test_webapi_vtrade.py``;
the LLM is always a fake injected through the ``llm_service`` seam so no test
ever constructs the real guarded Gemini service (offline-first, ``AGENTS.md``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from investment_assistant.llm.service import LlmResponse
from investment_assistant.webapi import virtual_trade as vtrade_api
from investment_assistant.webapi.service import available_routes, handle_api

_BARS_HEADER = "ticker,date,open,high,low,close,volume\n"
_JPX_HEADER = (
    "日付,コード,銘柄名,市場・商品区分,33業種コード,33業種区分,17業種コード,17業種区分,規模コード,規模区分\n"
)
_JPX_ROWS = "20260531,1000,テスト電力,プライム（内国株式）,50,電気・ガス業,1,X,6,Y\n"


def _bars_rows(ticker: str, n: int, start_price: float, end_price: float) -> str:
    start = date(2026, 1, 1)
    step = (end_price - start_price) / (n - 1) if n > 1 else 0.0
    lines = []
    for i in range(n):
        price = start_price + step * i
        d = (start + timedelta(days=i)).isoformat()
        lines.append(f"{ticker},{d},{price},{price},{price},{price},200000\n")
    return "".join(lines)


class _FakeLlm:
    """Minimal LlmServiceProtocol stand-in recording the prompt it was given."""

    def __init__(self, response: LlmResponse) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.task_types: list[str] = []

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        _ = priority
        self.task_types.append(task_type)
        self.prompts.append(prompt)
        return self.response


@pytest.fixture(autouse=True)
def _reset_vtrade_data_source() -> Iterator[None]:
    yield
    vtrade_api.reset_data_source()


def _configure(tmp_path: Path, *, llm: object | None = None) -> None:
    bars_path = tmp_path / "daily_bars.csv"
    bars_path.write_text(_BARS_HEADER + _bars_rows("1000", 40, 1000.0, 1200.0), encoding="utf-8")
    jpx_path = tmp_path / "jpx.csv"
    jpx_path.write_text(_JPX_HEADER + _JPX_ROWS, encoding="utf-8")
    vtrade_api.configure(
        daily_bars_path=bars_path,
        jpx_master_path=jpx_path,
        store_path=tmp_path / "vtrade.sqlite",
        llm_service=llm,
    )


def _place_user_buy() -> None:
    status, payload = handle_api(
        "POST", "/api/vtrade/order", {"ticker": "1000", "side": "buy", "shares": 100}
    )
    assert status == 200 and payload["ok"] is True


def test_advice_route_is_registered() -> None:
    assert "POST /api/vtrade/advice" in available_routes()


def test_advice_local_template_when_real_api_off(tmp_path: Path) -> None:
    _configure(tmp_path)
    _place_user_buy()

    status, payload = handle_api(
        "POST", "/api/vtrade/advice", {"account": "user", "call_real_api": False}
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["account"] == "user"
    assert payload["source"] == "local_template"
    assert "投資助言ではありません" in payload["advice"]
    assert payload["disclaimer"]
    positions = payload["context"]["positions"]
    assert len(positions) == 1
    assert positions[0]["ticker"] == "1000"
    assert positions[0]["stop_loss_price"] < positions[0]["avg_cost"]
    assert positions[0]["take_profit_price"] > positions[0]["avg_cost"]
    assert payload["context"]["timing"]["horizon_bars"] == 5


def test_advice_uses_llm_when_available(tmp_path: Path) -> None:
    fake = _FakeLlm(LlmResponse("LLMからの助言です。", "gemini", "key123"))
    _configure(tmp_path, llm=fake)
    _place_user_buy()

    status, payload = handle_api(
        "POST", "/api/vtrade/advice", {"account": "user", "call_real_api": True}
    )

    assert status == 200
    assert payload["advice"] == "LLMからの助言です。"
    assert payload["source"] == "gemini"
    assert fake.task_types == ["trade_advice"]
    # The prompt must carry the deterministic facts (grounding) and the
    # non-assertive-advice instruction (compliance).
    prompt = fake.prompts[0]
    assert "断定的な売買推奨は禁止" in prompt
    assert "1000" in prompt
    assert "売りタイミング勝率" in prompt


def test_advice_falls_back_when_llm_skips(tmp_path: Path) -> None:
    fake = _FakeLlm(
        LlmResponse("", "fallback:skip_llm:monthly_limit_reached", "k", warning=True, skipped=True)
    )
    _configure(tmp_path, llm=fake)
    _place_user_buy()

    status, payload = handle_api("POST", "/api/vtrade/advice", {"call_real_api": True})

    assert status == 200
    assert payload["source"] == "local_fallback:fallback:skip_llm:monthly_limit_reached"
    assert "投資助言ではありません" in payload["advice"]


def test_advice_never_echoes_prompt_on_local_summary_fallback(tmp_path: Path) -> None:
    # LlmService's on_error local_summary mode returns the (normalized) prompt
    # itself as .text -- the endpoint must not present that as advice.
    fake = _FakeLlm(
        LlmResponse(
            "あなたは投資学習用シミュレーション（仮想取引）のアドバイザーです。…",
            "fallback:local_summary:error",
            "k",
            warning=True,
        )
    )
    _configure(tmp_path, llm=fake)
    _place_user_buy()

    status, payload = handle_api("POST", "/api/vtrade/advice", {"call_real_api": True})

    assert status == 200
    assert payload["source"].startswith("local_fallback:")
    assert "アドバイザーです" not in payload["advice"]


def test_advice_ai_account_ticks_autopilot_first(tmp_path: Path) -> None:
    _configure(tmp_path)

    status, payload = handle_api(
        "POST", "/api/vtrade/advice", {"account": "ai", "call_real_api": False}
    )

    assert status == 200
    assert payload["account"] == "ai"
    # The lazy tick ran: with a qualifying candidate the AI book bought it.
    assert payload["context"]["trade_count"] >= 1


def test_advice_invalid_account_is_api_error(tmp_path: Path) -> None:
    _configure(tmp_path)

    status, _payload = handle_api("POST", "/api/vtrade/advice", {"account": "bogus"})

    assert status == 400
