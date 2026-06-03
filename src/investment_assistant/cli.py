"""Command-line utilities for operating the investment assistant foundation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.llm.factory import (
    DEFAULT_GEMINI_CONFIG_PATH,
    build_llm_service,
    load_gemini_runtime_config,
)
from investment_assistant.llm.gemini_client import TextGenerationClient


@dataclass(frozen=True)
class BudgetReport:
    """CLI-friendly budget report."""

    model: str
    daily_limit: int
    monthly_limit: int
    hard_daily_limit: int
    hard_monthly_limit: int
    daily_used: int
    monthly_used: int
    daily_remaining: int
    monthly_remaining: int
    warning: bool


class EchoClient:
    """Local fake client used by the smoke command without calling Gemini."""

    def generate(self, prompt: str, *, model: str) -> str:
        return f"[smoke:{model}] {prompt}"


def build_budget_report(config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH) -> BudgetReport:
    """Build a current UTC daily/monthly budget report without calling Gemini."""

    runtime = load_gemini_runtime_config(config_path)
    service = build_llm_service(config_path, client=EchoClient())
    now = datetime.now(UTC)
    daily_used = service.budget_guard.count_daily(now)
    monthly_used = service.budget_guard.count_monthly(now)
    hard_daily = int(runtime.budget.daily_request_limit * runtime.budget.hard_stop_threshold_ratio)
    hard_monthly = int(
        runtime.budget.monthly_request_limit * runtime.budget.hard_stop_threshold_ratio
    )
    warning = (
        daily_used >= runtime.budget.daily_request_limit * runtime.budget.warning_threshold_ratio
        or monthly_used
        >= runtime.budget.monthly_request_limit * runtime.budget.warning_threshold_ratio
    )
    return BudgetReport(
        model=runtime.model,
        daily_limit=runtime.budget.daily_request_limit,
        monthly_limit=runtime.budget.monthly_request_limit,
        hard_daily_limit=hard_daily,
        hard_monthly_limit=hard_monthly,
        daily_used=daily_used,
        monthly_used=monthly_used,
        daily_remaining=max(0, hard_daily - daily_used),
        monthly_remaining=max(0, hard_monthly - monthly_used),
        warning=warning,
    )


def run_smoke(
    *,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    task_type: str = "rag_answer",
    prompt: str = "Gemini budget guard smoke test",
    client: TextGenerationClient | None = None,
) -> dict[str, object]:
    """Run a no-network smoke generation through the guarded service path."""

    service = build_llm_service(config_path, client=client or EchoClient())
    response = service.generate(task_type=task_type, prompt=prompt)
    return {
        "text": response.text,
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def run_gemini_live(
    *,
    config_path: str | Path = DEFAULT_GEMINI_CONFIG_PATH,
    task_type: str = "rag_answer",
    prompt: str,
) -> dict[str, object]:
    """Manually call the real Gemini API through the guarded service path."""

    service = build_llm_service(config_path)
    response = service.generate(task_type=task_type, prompt=prompt)
    return {
        "text": response.text,
        "source": response.source,
        "warning": response.warning,
        "skipped": response.skipped,
        "cache_key": response.cache_key,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""

    parser = argparse.ArgumentParser(prog="investment-assistant")
    parser.add_argument("--config", default=str(DEFAULT_GEMINI_CONFIG_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    budget_parser = subparsers.add_parser("budget", help="Show Gemini budget usage")
    budget_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    smoke_parser = subparsers.add_parser("smoke", help="Run a no-network LLM service smoke check")
    smoke_parser.add_argument("--task-type", default="rag_answer")
    smoke_parser.add_argument("--prompt", default="Gemini budget guard smoke test")

    live_parser = subparsers.add_parser(
        "gemini-live",
        help="Manually call the real Gemini API through the guarded service",
    )
    live_parser.add_argument("--task-type", default="rag_answer")
    live_parser.add_argument("--prompt", required=True)
    live_parser.add_argument(
        "--call-real-api",
        action="store_true",
        help="Required safety acknowledgement because this consumes Gemini quota",
    )

    args = parser.parse_args(argv)
    config_path = str(args.config)

    if args.command == "budget":
        report = build_budget_report(config_path)
        if bool(args.json):
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            print(_format_budget_report(report))
        return 0

    if args.command == "smoke":
        result = run_smoke(
            config_path=config_path,
            task_type=str(args.task_type),
            prompt=str(args.prompt),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "gemini-live":
        if not bool(args.call_real_api):
            print("Refusing to call Gemini API without --call-real-api.")
            return 2
        result = run_gemini_live(
            config_path=config_path,
            task_type=str(args.task_type),
            prompt=str(args.prompt),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 2


def _format_budget_report(report: BudgetReport) -> str:
    return "\n".join(
        (
            f"model: {report.model}",
            f"daily: {report.daily_used}/{report.hard_daily_limit} "
            f"hard-stop requests used ({report.daily_remaining} remaining)",
            f"monthly: {report.monthly_used}/{report.hard_monthly_limit} "
            f"hard-stop requests used ({report.monthly_remaining} remaining)",
            f"warning: {str(report.warning).lower()}",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
