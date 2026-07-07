"""Tests for investment_assistant.webapi.server static-file helpers."""


def test_static_directory_index_resolves(tmp_path, monkeypatch):
    """Directory static paths should serve their own index.html before SPA fallback."""
    from investment_assistant.webapi import server

    dist = tmp_path / "dist"
    dashboard = dist / "market-dashboard"
    dashboard.mkdir(parents=True)
    (dist / "index.html").write_text("spa", encoding="utf-8")
    (dashboard / "index.html").write_text("dashboard", encoding="utf-8")

    monkeypatch.setattr(server, "FRONTEND_DIST", dist)

    assert server._resolve_static_target("/market-dashboard/") == dashboard / "index.html"
    assert server._resolve_static_target("/market-dashboard") == dashboard / "index.html"


def test_cache_control_policy_for_static_paths():
    """index.html must revalidate; hashed assets may cache forever."""
    from investment_assistant.webapi import server

    assert server._cache_control_for("/") == "no-cache"
    assert server._cache_control_for("/index.html") == "no-cache"
    assert server._cache_control_for("/index.html?v=2") == "no-cache"
    assert (
        server._cache_control_for("/assets/index-DhXsJDnr.js")
        == "public, max-age=31536000, immutable"
    )
