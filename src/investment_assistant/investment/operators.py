"""Human-readable operator catalog for deterministic investment workflows."""

from __future__ import annotations

from datetime import UTC, datetime

from investment_assistant.investment.candidates import FUND_SCORE_WEIGHTS
from investment_assistant.rag.search import (
    DEFAULT_HYBRID_ALPHA,
    DEFAULT_MAX_PER_SOURCE,
    DEFAULT_RRF_K,
)
from investment_assistant.scoring.stock import StockScoreWeights


def operator_catalog() -> dict[str, object]:
    """Return formulas and boundaries used by the investment-only MVP.

    This catalog is intentionally static and deterministic. It gives the UI a
    single place to explain what is calculated by rules, what is retrieved as
    evidence, and what is never automated.
    """

    stock_weights = StockScoreWeights().normalized()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "version": "investment_operator_catalog_v1",
        "auto_trading": False,
        "call_real_api": False,
        "non_advisory_boundary": (
            "候補抽出、スコア、RAG検索は比較材料の提示に限定します。"
            "売買推奨、断定的な投資判断、自動注文は行いません。"
        ),
        "groups": [
            {
                "key": "portfolio_analysis",
                "label": "保有分析",
                "purpose": (
                    "手入力またはCSVの保有データから、評価額、損益、集中度、"
                    "NISA利用額を再現可能に集計する。"
                ),
                "operators": [
                    {
                        "key": "market_value",
                        "label": "評価額",
                        "formula": "quantity * (current_price or avg_cost)",
                        "inputs": ["quantity", "current_price", "avg_cost"],
                        "output": "market_value",
                    },
                    {
                        "key": "unrealized_pnl",
                        "label": "評価損益",
                        "formula": "market_value - quantity * avg_cost",
                        "inputs": ["quantity", "avg_cost", "current_price"],
                        "output": "unrealized_pnl",
                    },
                    {
                        "key": "position_share",
                        "label": "集中度",
                        "formula": "holding.market_value / portfolio.market_value",
                        "inputs": ["holding.market_value", "portfolio.market_value"],
                        "output": "share_pct",
                    },
                    {
                        "key": "nisa_used_cost_basis",
                        "label": "NISA利用額",
                        "formula": "sum(quantity * avg_cost where tax_wrapper starts with nisa)",
                        "inputs": ["quantity", "avg_cost", "tax_wrapper"],
                        "output": "nisa.used_cost_basis",
                    },
                ],
            },
            {
                "key": "stock_scoring",
                "label": "日本株スコア",
                "purpose": "EDINET由来の財務CSVを、透明な重み付きルールで比較材料に変換する。",
                "model_version": "stock_score_balanced_v1",
                "formula": "sum(normalized_component * normalized_weight)",
                "weights": [
                    {
                        "key": "dividend_level",
                        "label": "配当水準",
                        "weight": round(stock_weights.dividend_level, 4),
                    },
                    {
                        "key": "dividend_trend",
                        "label": "配当トレンド",
                        "weight": round(stock_weights.dividend_trend, 4),
                    },
                    {
                        "key": "dividend_safety",
                        "label": "減配耐性",
                        "weight": round(stock_weights.dividend_safety, 4),
                    },
                    {
                        "key": "equity_ratio",
                        "label": "自己資本比率",
                        "weight": round(stock_weights.equity_ratio, 4),
                    },
                    {
                        "key": "operating_cf",
                        "label": "営業CFトレンド",
                        "weight": round(stock_weights.operating_cf, 4),
                    },
                ],
                "operators": [
                    {
                        "key": "exclude_dividend_cut",
                        "label": "減配除外",
                        "formula": "cut_count == 0 when enabled",
                        "inputs": ["dividend_series"],
                        "output": "filter_pass",
                    },
                    {
                        "key": "min_equity_ratio",
                        "label": "自己資本比率しきい値",
                        "formula": "latest_equity_ratio >= threshold",
                        "inputs": ["latest_equity_ratio", "threshold"],
                        "output": "filter_pass",
                    },
                ],
            },
            {
                "key": "fund_scoring",
                "label": "投信プロファイル",
                "purpose": (
                    "ユーザー入力または契約済みproviderの投信プロファイルを"
                    "比較材料としてスコア化する。"
                ),
                "model_version": "fund_weighted_v1",
                "formula": "sum(weight * normalized_score)",
                "weights": [
                    {
                        "key": key,
                        "label": _fund_weight_label(key),
                        "weight": round(value, 4),
                    }
                    for key, value in FUND_SCORE_WEIGHTS.items()
                ],
                "operators": [
                    {
                        "key": "expense_ratio_score",
                        "label": "信託報酬スコア",
                        "formula": "max(0, 1 - expense_ratio_percent / 1.0)",
                        "inputs": ["expense_ratio"],
                        "output": "normalized_score",
                    },
                    {
                        "key": "nisa_eligible_score",
                        "label": "NISA対象",
                        "formula": "1 if nisa_eligible else 0",
                        "inputs": ["nisa_eligible"],
                        "output": "normalized_score",
                    },
                    {
                        "key": "diversification_score",
                        "label": "分散度",
                        "formula": "user diversification_score or conservative asset_class hint",
                        "inputs": ["diversification_score", "asset_class"],
                        "output": "normalized_score",
                    },
                ],
            },
            {
                "key": "rag_search",
                "label": "RAG検索",
                "purpose": "ローカル文書から根拠候補を探し、LLMに渡す前の出典と順位を可視化する。",
                "operators": [
                    {
                        "key": "query_decomposition",
                        "label": "クエリ分解",
                        "formula": "original query + separator phrases + useful tokens",
                        "inputs": ["query"],
                        "output": "query_variants",
                    },
                    {
                        "key": "hybrid_blend",
                        "label": "ハイブリッド検索",
                        "formula": (
                            f"{DEFAULT_HYBRID_ALPHA} * semantic_score + "
                            f"{1 - DEFAULT_HYBRID_ALPHA} * lexical_score"
                        ),
                        "inputs": ["BM25/keyword score", "embedding cosine score"],
                        "output": "blended_score",
                    },
                    {
                        "key": "reciprocal_rank_fusion",
                        "label": "RRF順位統合",
                        "formula": f"sum(1 / ({DEFAULT_RRF_K} + rank))",
                        "inputs": ["ranked results per query"],
                        "output": "fused_score",
                    },
                    {
                        "key": "source_diversity",
                        "label": "出典分散",
                        "formula": f"max_per_source <= {DEFAULT_MAX_PER_SOURCE}",
                        "inputs": ["source", "near-duplicate fingerprint"],
                        "output": "selected_context",
                    },
                ],
            },
            {
                "key": "report_evidence",
                "label": "レポート根拠",
                "purpose": "重要KPIに計算式、出典、最終更新、免責を結びつけて公開前検算を行う。",
                "operators": [
                    {
                        "key": "claim_evidence_check",
                        "label": "claim-evidence検査",
                        "formula": "all important KPI claim_keys must have evidence rows",
                        "inputs": ["report.kpis", "report.evidence"],
                        "output": "audit_status",
                    },
                    {
                        "key": "disclaimer_check",
                        "label": "免責検査",
                        "formula": "report.disclaimer exists and auto_trading is false",
                        "inputs": ["report"],
                        "output": "audit_status",
                    },
                ],
            },
        ],
    }


def _fund_weight_label(key: str) -> str:
    labels = {
        "expense_ratio": "低コスト性",
        "nisa_eligible": "NISA対象",
        "diversification": "分散度",
        "distribution_policy": "分配方針",
    }
    return labels.get(key, key)
