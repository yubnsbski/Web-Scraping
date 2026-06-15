"""Provider-use policy for production-safe data handling."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass

RUNTIME_MODE_ENV = "INVESTMENT_ASSISTANT_RUNTIME_MODE"
CONTRACTED_PROVIDERS_ENV = "INVESTMENT_ASSISTANT_CONTRACTED_PROVIDERS"

_ALWAYS_ALLOWED = {
    "edinet",
    "manual",
    "user_csv",
    "user_input",
    "yahoo_finance_manual",
    "contracted",
}
_DEFAULT_LEDGER_PROVIDERS = (
    "edinet",
    "user_csv",
    "manual",
    "stooq_public_csv",
    "yfinance",
    "yahoo_finance_manual",
    "jquants",
    "alpha_vantage",
    "contracted",
)
_PROVIDER_METADATA: dict[str, dict[str, str]] = {
    "edinet": {
        "category": "public_disclosure",
        "primary_use": "Japanese issuer filings and financial facts",
        "recommended_use": "primary_evidence",
    },
    "user_csv": {
        "category": "user_supplied",
        "primary_use": "User-provided holdings, prices, and fund fields",
        "recommended_use": "single_user_input",
    },
    "manual": {
        "category": "user_supplied",
        "primary_use": "Manual entry and corrections",
        "recommended_use": "single_user_input",
    },
    "stooq_public_csv": {
        "category": "public_market_csv",
        "primary_use": "Development market price fixture",
        "recommended_use": "development_only",
    },
    "yfinance": {
        "category": "market_data_library",
        "primary_use": "Research and prototype market data",
        "recommended_use": "development_only",
    },
    "yahoo_finance_manual": {
        "category": "user_supplied_market_data",
        "primary_use": "User-entered Yahoo Finance quote CSV for personal local use",
        "recommended_use": "manual_single_user_only",
    },
    "jquants": {
        "category": "market_data_api",
        "primary_use": "Japanese market, financial, and dividend data",
        "recommended_use": "contract_required",
    },
    "alpha_vantage": {
        "category": "market_data_api",
        "primary_use": "Supplemental market data",
        "recommended_use": "contract_required",
    },
    "contracted": {
        "category": "contracted_provider",
        "primary_use": "Provider explicitly covered by a commercial agreement",
        "recommended_use": "production_if_contract_allows",
    },
}


@dataclass(frozen=True)
class ProviderPolicy:
    provider_id: str
    runtime_mode: str
    production_allowed: bool
    commercial_use: str
    redistribution: str
    license_note: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def provider_policy(provider_id: str, *, runtime_mode: str | None = None) -> ProviderPolicy:
    normalized = (provider_id or "unknown").strip().lower()
    mode = (runtime_mode or os.getenv(RUNTIME_MODE_ENV) or "development").strip().lower()
    contracted = _contracted_provider_ids()
    production_allowed = (
        mode != "production" or normalized in _ALWAYS_ALLOWED or normalized in contracted
    )
    if production_allowed:
        note = "provider is allowed for this runtime mode"
    else:
        note = "provider is not marked as contracted; production use is blocked"
    return ProviderPolicy(
        provider_id=normalized,
        runtime_mode=mode,
        production_allowed=production_allowed,
        commercial_use="allowed_if_contracted" if normalized in contracted else "unknown",
        redistribution="allowed_if_contracted" if normalized in contracted else "unknown",
        license_note=note,
    )


def ensure_provider_allowed(provider_id: str, *, runtime_mode: str | None = None) -> ProviderPolicy:
    policy = provider_policy(provider_id, runtime_mode=runtime_mode)
    if not policy.production_allowed:
        raise ValueError(
            f"Provider '{policy.provider_id}' is not allowed in production mode without a contract."
        )
    return policy


def provider_policy_ledger(
    *,
    runtime_mode: str | None = None,
    provider_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    """Return a deterministic provider policy ledger for review UI/API."""

    providers = _normalized_provider_ids(provider_ids)
    rows: list[dict[str, object]] = []
    for provider_id in providers:
        policy = provider_policy(provider_id, runtime_mode=runtime_mode)
        metadata = _PROVIDER_METADATA.get(
            policy.provider_id,
            {
                "category": "unknown",
                "primary_use": "Unregistered provider id",
                "recommended_use": "contract_required",
            },
        )
        rows.append(
            {
                **policy.to_dict(),
                **metadata,
                "runtime_decision": (
                    "allowed" if policy.production_allowed else "blocked_until_contracted"
                ),
            }
        )
    return {
        "runtime_mode": rows[0]["runtime_mode"] if rows else _runtime_mode(runtime_mode),
        "providers": rows,
        "count": len(rows),
        "contracted_provider_count": len(_contracted_provider_ids()),
        "contracted_providers_env": CONTRACTED_PROVIDERS_ENV,
        "auto_trading": False,
        "call_real_api": False,
    }


def _contracted_provider_ids() -> set[str]:
    raw = os.getenv(CONTRACTED_PROVIDERS_ENV, "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _runtime_mode(runtime_mode: str | None) -> str:
    return (runtime_mode or os.getenv(RUNTIME_MODE_ENV) or "development").strip().lower()


def _normalized_provider_ids(provider_ids: Iterable[str] | None) -> list[str]:
    raw = list(provider_ids) if provider_ids is not None else list(_DEFAULT_LEDGER_PROVIDERS)
    out: list[str] = []
    seen: set[str] = set()
    for provider_id in raw:
        normalized = (provider_id or "unknown").strip().lower()
        if not normalized or normalized in seen:
            continue
        out.append(normalized)
        seen.add(normalized)
    return out
