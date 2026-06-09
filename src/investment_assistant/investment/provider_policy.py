"""Provider-use policy for production-safe data handling."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

RUNTIME_MODE_ENV = "INVESTMENT_ASSISTANT_RUNTIME_MODE"
CONTRACTED_PROVIDERS_ENV = "INVESTMENT_ASSISTANT_CONTRACTED_PROVIDERS"

_ALWAYS_ALLOWED = {"edinet", "manual", "user_csv", "user_input", "contracted"}


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


def _contracted_provider_ids() -> set[str]:
    raw = os.getenv(CONTRACTED_PROVIDERS_ENV, "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}
