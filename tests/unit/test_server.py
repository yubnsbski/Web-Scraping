"""Tests for web scraping and ensemble forecasting features."""

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

BASE_URL = "http://127.0.0.1:8080"


def make_request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Helper to make HTTP requests to the test server."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}

    body_bytes = None
    if body:
        body_bytes = json.dumps(body).encode("utf-8")

    req = Request(url, data=body_bytes, headers=headers, method=method)

    try:
        with urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as e:
        pytest.skip(f"Server not running: {e}")


class TestScrapeEndpoints:
    """Test web scraping endpoints."""

    def test_scrape_get_returns_sources(self):
        """GET /api/scrape should return available sources."""
        result = make_request("/api/scrape")

        assert "available_sources" in result
        assert "message" in result
        assert isinstance(result["available_sources"], list)
        assert len(result["available_sources"]) > 0
        assert "name" in result["available_sources"][0]
        assert "url" in result["available_sources"][0]

    def test_scrape_run_requires_sources(self):
        """POST /api/scrape/run with empty sources should fail."""
        result = make_request("/api/scrape/run", method="POST", body={"sources": []})

        assert "error" in result
        assert result["error"] == "sources_required"

    def test_scrape_run_success(self):
        """POST /api/scrape/run with valid sources should succeed."""
        sources = [{"name": "NTT IR", "url": "https://group.ntt/jp/ir/"}]
        result = make_request("/api/scrape/run", method="POST", body={"sources": sources})

        assert result["status"] == "success"
        assert "sources_processed" in result
        assert result["sources_processed"] == 1
        assert "results" in result
        assert isinstance(result["results"], list)


class TestForecastEndpoints:
    """Test ensemble forecasting endpoints."""

    def test_forecast_get_returns_methods(self):
        """GET /api/forecast should return available methods."""
        result = make_request("/api/forecast")

        assert "available_methods" in result
        assert isinstance(result["available_methods"], list)
        assert len(result["available_methods"]) > 0
        assert "sample_data" in result

    def test_forecast_evaluate_returns_models(self):
        """POST /api/forecast/evaluate should return model evaluations."""
        result = make_request("/api/forecast/evaluate", method="POST", body={})

        assert "series" in result
        assert "horizon" in result
        assert "observations" in result
        assert "best_model" in result
        assert "models" in result
        assert isinstance(result["models"], list)
        assert len(result["models"]) > 0

    def test_forecast_predict_single_horizon(self):
        """POST /api/forecast/predict with horizon=1 should return next prediction."""
        result = make_request("/api/forecast/predict", method="POST", body={"horizon": 1})

        assert "last_observed_return" in result
        assert "last_observed_value" in result
        assert "horizon" in result
        assert result["horizon"] == 1
        assert "ensemble_forecast" in result
        assert isinstance(result["ensemble_forecast"], list)
        assert len(result["ensemble_forecast"]) == 1
        assert "ensemble_weights" in result
        assert isinstance(result["ensemble_weights"], dict)

    def test_forecast_predict_multiple_horizons(self):
        """POST /api/forecast/predict with horizon=3 should return 3 predictions."""
        result = make_request("/api/forecast/predict", method="POST", body={"horizon": 3})

        assert result["horizon"] == 3
        assert len(result["ensemble_forecast"]) == 3


class TestChatEndpoints:
    """Test chat API endpoints for AI orchestration."""

    def test_chat_forecast_intent(self):
        """POST /api/chat with forecast keyword should detect forecast feature."""
        result = make_request("/api/chat", method="POST", body={"message": "S&P 500 の予測をして"})

        assert "role" in result
        assert result["role"] == "assistant"
        assert "content" in result
        assert "feature" in result
        assert result["feature"] == "forecast"
        assert "forecast_data" in result

    def test_chat_scraping_intent(self):
        """POST /api/chat with scraping keyword should detect scraping feature."""
        result = make_request("/api/chat", method="POST", body={"message": "NTT のデータを取得"})

        assert result["feature"] == "scraping"
        assert "available_sources" in result

    def test_chat_investment_analysis_intent(self):
        """POST /api/chat with investment keyword should detect analysis feature."""
        result = make_request("/api/chat", method="POST", body={"message": "S&P 500 について説明"})

        assert result["feature"] == "investment_analysis"
        assert "sp500_info" in result

    def test_chat_general_intent(self):
        """POST /api/chat with general message should return general feature."""
        result = make_request("/api/chat", method="POST", body={"message": "こんにちは"})

        assert result["feature"] == "general"
        assert "suggestions" in result

    def test_chat_requires_message(self):
        """POST /api/chat without message should fail."""
        result = make_request("/api/chat", method="POST", body={"message": ""})

        assert "error" in result


class TestUIIntegration:
    """Test UI availability and basic integration."""

    def test_index_html_loads(self):
        """Main index.html should load successfully."""
        url = f"{BASE_URL}/"
        req = Request(url)

        try:
            with urlopen(req) as response:
                content = response.read().decode("utf-8")
                assert "Investment Assistant" in content
                assert "AI駆動型投資支援チャット" in content
                assert "アンサンブル予測" in content
        except URLError:
            pytest.skip("Server not running")

    def test_app_css_loads(self):
        """app.css should load successfully."""
        url = f"{BASE_URL}/app.css"
        req = Request(url)

        try:
            with urlopen(req) as response:
                content = response.read().decode("utf-8")
                assert "color-scheme: dark" in content or "body" in content
        except URLError:
            pytest.skip("Server not running")

    def test_app_js_loads(self):
        """app.js should load successfully."""
        url = f"{BASE_URL}/app.js"
        req = Request(url)

        try:
            with urlopen(req) as response:
                content = response.read().decode("utf-8")
                assert "fetch" in content or "sendMessage" in content
        except URLError:
            pytest.skip("Server not running")
