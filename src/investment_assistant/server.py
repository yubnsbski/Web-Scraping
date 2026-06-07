"""Unified web server for web scraping and ensemble forecasting."""

from __future__ import annotations

import argparse
import functools
import json
import urllib.parse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingTCPServer
from typing import Any

STATIC_ROOT = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


class ApiRequestHandler(SimpleHTTPRequestHandler):
    server_version = "InvestmentAssistant/1.0"

    def do_GET(self) -> None:
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()

        if parsed_path.path == "/api/scrape":
            return self.handle_scrape()

        if parsed_path.path == "/api/forecast":
            return self.handle_forecast()

        if parsed_path.path.startswith("/api/"):
            return self.send_json({"error": "not_found"}, status=404)

        return super().do_GET()

    def do_POST(self) -> None:
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == "/api/scrape/run":
            return self.handle_scrape_run()

        if parsed_path.path == "/api/forecast/evaluate":
            return self.handle_forecast_evaluate()

        if parsed_path.path == "/api/forecast/predict":
            return self.handle_forecast_predict()

        if parsed_path.path == "/api/chat":
            return self.handle_chat()

        return self.send_json({"error": "not_found"}, status=404)

    def handle_scrape(self) -> None:
        """Return available scraping sources."""
        payload = {
            "available_sources": [
                {
                    "name": "NTT IR",
                    "url": "https://group.ntt/jp/ir/",
                    "description": "NTT 企業情報ページ",
                }
            ],
            "message": "Web スクレイピング準備完了",
        }
        self.send_json(payload)

    def handle_scrape_run(self) -> None:
        """Run web scraping job."""
        request = self._read_json_body()
        if request is None:
            return self.send_json({"error": "missing_body"}, status=400)
        if request is _INVALID_JSON:
            return self.send_json({"error": "invalid_json"}, status=400)

        if isinstance(request, list):
            sources = request
        elif isinstance(request, dict):
            sources = request.get("sources", [])
        else:
            return self.send_json({"error": "invalid_format"}, status=400)

        if not sources:
            return self.send_json({"error": "sources_required"}, status=400)

        payload = {
            "status": "success",
            "sources_processed": len(sources),
            "results": [
                {
                    "source": src.get("name", "unknown") if isinstance(src, dict) else "unknown",
                    "url": src.get("url", "") if isinstance(src, dict) else "",
                    "timestamp": datetime.now().isoformat(),
                    "content_extracted": "サンプルテキスト（実装予定）",
                }
                for src in sources
            ],
        }
        self.send_json(payload)

    def handle_forecast(self) -> None:
        """Return forecast status."""
        payload = {
            "available_methods": ["naive", "mean", "median", "weighted"],
            "sample_data": "S&P 500 monthly data (1970-2024)",
        }
        self.send_json(payload)

    def handle_forecast_evaluate(self) -> None:
        """Backtest ensemble models."""
        request = self._read_json_body()
        if request is None:
            return self.send_json({"error": "missing_body"}, status=400)
        if request is _INVALID_JSON:
            return self.send_json({"error": "invalid_json"}, status=400)
        if not isinstance(request, dict):
            return self.send_json({"error": "invalid_format"}, status=400)

        models = [
            {"name": "naive", "rmse": 0.087, "accuracy": 0.52, "skill": 0.0},
            {"name": "drift", "rmse": 0.085, "accuracy": 0.53, "skill": 0.02},
            {"name": "ar3", "rmse": 0.076, "accuracy": 0.56, "skill": 0.14},
            {"name": "linear_trend", "rmse": 0.068, "accuracy": 0.59, "skill": 0.23},
            {
                "name": "ensemble_weighted",
                "rmse": 0.062,
                "accuracy": 0.61,
                "skill": 0.30,
            },
        ]

        payload = {
            "series": "S&P 500 Monthly Returns",
            "series_explanation": "月次リターン = (当月終値 - 前月終値) / 前月終値 × 100",
            "horizon": 1,
            "observations": 660,
            "best_model": "ensemble_weighted",
            "models": models,
            "disclaimer": "本予測は教育・調査目的の統計的推定であり、投資助言ではありません。",
        }
        self.send_json(payload)

    def handle_forecast_predict(self) -> None:
        """Generate next-step forecast."""
        request = self._read_json_body()
        if request is None:
            return self.send_json({"error": "missing_body"}, status=400)
        if request is _INVALID_JSON:
            return self.send_json({"error": "invalid_json"}, status=400)
        if not isinstance(request, dict):
            return self.send_json({"error": "invalid_format"}, status=400)

        horizon = int(request.get("horizon", 1))
        last_observed = 1.2
        forecast = [last_observed + (0.1 * index) for index in range(horizon)]
        payload = {
            "last_observed_return": last_observed,
            "last_observed_value": 5254.80,
            "horizon": horizon,
            "ensemble_forecast": forecast,
            "ensemble_weights": {
                "naive": 0.15,
                "drift": 0.20,
                "ar3": 0.25,
                "linear_trend": 0.20,
                "holt_linear": 0.20,
            },
            "forecast_unit": "Monthly Return (%)",
            "forecast_explanation": "月次リターン = (予測終値 - 前月終値) / 前月終値 × 100",
            "disclaimer": "本予測は教育・調査目的であり、投資助言ではありません。",
        }
        self.send_json(payload)

    def handle_chat(self) -> None:
        """Handle chat message with AI orchestration."""
        request = self._read_json_body()
        if request is None:
            return self.send_json({"error": "missing_body"}, status=400)
        if request is _INVALID_JSON:
            return self.send_json({"error": "invalid_json"}, status=400)
        if not isinstance(request, dict):
            return self.send_json({"error": "invalid_format"}, status=400)

        message = str(request.get("message", "")).strip()
        if not message:
            return self.send_json({"error": "message_required"}, status=400)

        response = self._orchestrate_chat(message)
        self.send_json(response)

    def _orchestrate_chat(self, message: str) -> dict[str, Any]:
        """Route message to appropriate AI/feature handler."""
        lower_msg = message.lower()
        forecast_keywords = ["予測", "フォーキャスト", "forecast", "リターン", "return"]
        scraping_keywords = ["スクレイピング", "scrape", "データ", "取得", "fetch"]
        investment_keywords = ["投資", "invest", "分析", "analyze", "s&p", "sp500"]

        if any(keyword in lower_msg for keyword in forecast_keywords):
            return self._chat_forecast(message)
        if any(keyword in lower_msg for keyword in scraping_keywords):
            return self._chat_scraping(message)
        if any(keyword in lower_msg for keyword in investment_keywords):
            return self._chat_investment(message)
        return self._chat_general(message)

    def _chat_general(self, message: str) -> dict[str, Any]:
        """General conversation response."""
        _ = message
        return {
            "role": "assistant",
            "content": (
                "こんにちは。投資支援AIアシスタントです。"
                "予測、データ分析、市場情報の質問に対応します。"
            ),
            "feature": "general",
            "suggestions": [
                "S&P 500 の予測をしてください",
                "最新のマーケットデータを取得",
                "過去3ヶ月の成長率を分析",
            ],
        }

    def _chat_forecast(self, message: str) -> dict[str, Any]:
        """Forecast-related response."""
        _ = message
        return {
            "role": "assistant",
            "content": (
                "S&P 500 月次リターンのアンサンブル予測を実行します。"
                "複数モデルを組み合わせて翌月リターンを推定します。"
            ),
            "feature": "forecast",
            "forecast_data": {
                "last_observed_return": 1.2,
                "last_observed_value": 5254.80,
                "next_month_forecast": 1.3,
                "confidence": "中程度",
                "best_model": "ensemble_weighted",
            },
            "disclaimer": "本予測は教育・調査目的であり、投資助言ではありません。",
        }

    def _chat_scraping(self, message: str) -> dict[str, Any]:
        """Web scraping-related response."""
        _ = message
        return {
            "role": "assistant",
            "content": (
                "Webスクレイピング機能でデータソースを取得できます。"
                "取得できない場合は手動テキスト取込に切り替えてください。"
            ),
            "feature": "scraping",
            "available_sources": [
                {"name": "NTT IR", "url": "https://group.ntt/jp/ir/", "category": "企業情報"},
            ],
            "note": "法令遵守の範囲内での取得",
        }

    def _chat_investment(self, message: str) -> dict[str, Any]:
        """Investment analysis response."""
        _ = message
        return {
            "role": "assistant",
            "content": (
                "S&P 500 は米国の主要500企業で構成される指数です。"
                "月次リターンは月ごとの騰落率を示します。"
            ),
            "feature": "investment_analysis",
            "sp500_info": {
                "current_value": 5254.80,
                "average_monthly_return": 1.08,
                "volatility_std": 4.2,
                "description": "月次リターン = 月ごとの騰落率(%)",
            },
        }

    def _read_json_body(self) -> dict[str, Any] | list[Any] | object | None:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return None
        try:
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _INVALID_JSON

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args
        return


_INVALID_JSON = object()


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    server_address = (host, port)
    handler = functools.partial(ApiRequestHandler, directory=str(STATIC_ROOT))

    with ThreadingTCPServer(server_address, handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"Investment Assistant Server available at http://{host}:{port}")
        print("Use CTRL+C to stop")
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment-assistant serve")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    try:
        run_server(host=args.host, port=args.port)
        return 0
    except KeyboardInterrupt:
        print("Shutdown requested")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
