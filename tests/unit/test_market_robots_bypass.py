from __future__ import annotations

from investment_assistant.portfolio import _market_common as mc


def test_robots_bypass_env_parsing(monkeypatch) -> None:
    monkeypatch.delenv(mc.MARKET_ROBOTS_BYPASS_ENV, raising=False)
    assert mc.robots_bypass_enabled() is False
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv(mc.MARKET_ROBOTS_BYPASS_ENV, truthy)
        assert mc.robots_bypass_enabled() is True
    monkeypatch.setenv(mc.MARKET_ROBOTS_BYPASS_ENV, "0")
    assert mc.robots_bypass_enabled() is False


def test_default_fetch_passes_respect_robots_from_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeDoc:
        html = "ok"

    class _FakeFetcher:
        def fetch_document(self, url: str, *, respect_robots: bool = True) -> _FakeDoc:
            captured["respect_robots"] = respect_robots
            return _FakeDoc()

    monkeypatch.setattr(mc, "SafeFetcher", lambda: _FakeFetcher())

    monkeypatch.delenv(mc.MARKET_ROBOTS_BYPASS_ENV, raising=False)
    assert mc.default_fetch("u") == "ok"
    assert captured["respect_robots"] is True  # robots honored by default

    monkeypatch.setenv(mc.MARKET_ROBOTS_BYPASS_ENV, "1")
    mc.default_fetch("u")
    assert captured["respect_robots"] is False  # personal-use bypass enabled
