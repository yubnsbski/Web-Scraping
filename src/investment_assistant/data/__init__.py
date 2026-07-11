"""High-quality investment data pipeline: collect, validate, store, serve."""

from investment_assistant.data.consecutive_tracker import consecutive_raises, did_raise
from investment_assistant.data.dividend_scorer import (
    DividendScoreBreakdown,
    DividendScoreInput,
    DividendScoreWeights,
    DividendScoredStock,
    score_stock,
    score_stocks,
)
from investment_assistant.data.flick_collector import FlickCollector, FlickResult, FlickStatus, build_flick_collector
from investment_assistant.data.pipeline import DataPipeline, build_pipeline
from investment_assistant.data.sector_comparator import build_score_inputs, get_sector_peers
from investment_assistant.data.sprint_cache import SprintCache
from investment_assistant.data.store import InvestmentDataStore

__all__ = [
    # scoring
    "consecutive_raises",
    "did_raise",
    "DividendScoreBreakdown",
    "DividendScoreInput",
    "DividendScoreWeights",
    "DividendScoredStock",
    "score_stock",
    "score_stocks",
    "build_score_inputs",
    "get_sector_peers",
    # pipeline
    "DataPipeline",
    "build_pipeline",
    # flick (input track)
    "FlickCollector",
    "FlickResult",
    "FlickStatus",
    "build_flick_collector",
    # sprint (output track)
    "SprintCache",
    # store
    "InvestmentDataStore",
]
