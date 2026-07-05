"""Standard-library HTTP adapter serving the JSON API and the built frontend."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from investment_assistant.observability import configure_logging, get_logger
from investment_assistant.webapi.service import JsonDict, handle_api

_logger = get_logger("webapi.server")

# Built frontend assets (created by `npm run build` in web/). Optional.
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"

# JPX NeuroFinance dashboard — single hardcoded path, never derived from user input.
_JPX_DASHBOARD = Path(__file__).resolve().parents[3] / "JPX_NeuroFinance_Dashboard.html"

_MAX_BODY_BYTES = 2 * 1024 * 1024
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _resolve_static_target(request_path: str) -> Path:
    """Resolve a frontend static path, including directory index files."""
    rel = request_path.split("?", 1)[0].lstrip("/") or "index.html"
    frontend_root = FRONTEND_DIST.resolve()
    target = (frontend_root / rel).resolve()
    if frontend_root not in target.parents and target != frontend_root:
        return frontend_root / "index.html"
    if target.is_dir():
        directory_index = target / "index.html"
        if directory_index.is_file():
            return directory_index
        return frontend_root / "index.html"
    if not target.is_file():
        return frontend_root / "index.html"
    return target


class _Handler(BaseHTTPRequestHandler):
    server_version = "investment-assistant-webapi/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - required name
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - required name
        clean_path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if clean_path.startswith("/api/"):
            self._handle_api("GET")
            return
        if clean_path in ("/jpx", "/jpx/"):
            self._serve_jpx_dashboard()
            return
        self._serve_static()

    def do_POST(self) -> None:  # noqa: N802 - required name
        self._handle_api("POST")

    def _handle_api(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        body = self._read_json_body() if method == "POST" else None
        if body is _INVALID:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        status, payload = handle_api(method, path, body)  # type: ignore[arg-type]
        self._send_json(status, payload)

    def _read_json_body(self) -> JsonDict | None | object:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        if length > _MAX_BODY_BYTES:
            return _INVALID
        raw = self.rfile.read(length)
        if not raw:
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _INVALID
        return parsed if isinstance(parsed, dict) else _INVALID

    def _serve_jpx_dashboard(self) -> None:
        """Serve the pre-built JPX NeuroFinance HTML dashboard.

        Path is hardcoded — never derived from user input — so there is
        no path-traversal risk.
        """
        if not _JPX_DASHBOARD.is_file():
            self._send_json(
                404,
                {
                    "error": "JPX_NeuroFinance_Dashboard.html が見つかりません",
                    "hint": "POST /api/jpx/run でパイプラインを実行してください",
                },
            )
            return
        data = _JPX_DASHBOARD.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        # Scope the dashboard to same-origin only (no CORS needed for direct browser access)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self) -> None:
        if not FRONTEND_DIST.is_dir():
            self._send_json(
                404,
                {
                    "error": "frontend not built",
                    "hint": "cd web && npm install && npm run build, or use the Vite dev server",
                },
            )
            return
        target = _resolve_static_target(self.path)
        if not target.is_file():
            self._send_json(404, {"error": "not found"})
            return
        data = target.read_bytes()
        content_type = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: JsonDict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _cors(self) -> None:
        # Local single-user dashboard: allow the Vite dev server origin.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args: object) -> None:
        _logger.info("webapi %s", fmt % args)


_INVALID = object()


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the blocking HTTP server until interrupted."""

    configure_logging()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    _logger.info("serving on http://%s:%d (api under /api/, frontend if built)", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        _logger.info("shutting down")
    finally:
        httpd.server_close()
