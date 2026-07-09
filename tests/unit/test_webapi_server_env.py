"""serve() must load local env files so secrets survive server restarts."""

from __future__ import annotations

from unittest import mock

from investment_assistant.webapi import server


def test_serve_loads_local_env_before_binding() -> None:
    calls: list[str] = []

    with (
        mock.patch.object(
            server, "load_local_env_files", side_effect=lambda: calls.append("env")
        ),
        mock.patch.object(
            server,
            "ThreadingHTTPServer",
            side_effect=lambda *a, **k: calls.append("bind") or _FakeHttpd(),
        ),
    ):
        server.serve(host="127.0.0.1", port=0)

    assert calls == ["env", "bind"]


class _FakeHttpd:
    def serve_forever(self) -> None:
        return None

    def server_close(self) -> None:
        return None
