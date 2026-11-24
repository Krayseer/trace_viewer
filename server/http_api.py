"""HTTP request handling and static assets for the local trace viewer."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .api import api_response
from .application import TraceApplication
from .presentation import StageSources


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/viewer.css": ("viewer.css", "text/css"),
    "/viewer.js": ("viewer.js", "text/javascript"),
    "/viewer_ui.js": ("viewer_ui.js", "text/javascript"),
    "/viewer_table.js": ("viewer_table.js", "text/javascript"),
    "/viewer_orders_panel.js": ("viewer_orders_panel.js", "text/javascript"),
    "/fonts/roboto-cyrillic-wght-normal.woff2": ("fonts/roboto-cyrillic-wght-normal.woff2", "font/woff2"),
    "/fonts/roboto-latin-wght-normal.woff2": ("fonts/roboto-latin-wght-normal.woff2", "font/woff2"),
}


class TraceServer(ThreadingHTTPServer):
    application: TraceApplication
    sources: StageSources


class Handler(BaseHTTPRequestHandler):
    server: TraceServer

    def send_body(self, status: int, body: bytes, mime: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime if mime.startswith("font/") else f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_data(self, status: int, payload: list | dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_body(status, body, "application/json")

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path in ASSETS:
            filename, mime = ASSETS[url.path]
            self.send_body(200, (WEB_ROOT / filename).read_bytes(), mime)
            return
        queries = {key: vals[0] for key, vals in parse_qs(url.query).items()}
        self.send_data(*api_response(self.server.application, self.server.sources, url.path, queries))
