"""HTTP request handling and static assets for the local trace viewer."""

from __future__ import annotations

from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .application import TraceApplication, month_window
from .presentation import StageSources, coverage_payload, order_payload, source_payload, trace_payload


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
        app = self.server.application
        try:
            match url.path:
                case "/api/months":
                    result = [{"id": m, "label": label} for m, label in app.months()]
                case "/api/orders":
                    result = [order_payload(order) for order in app.orders(queries.get("month", app.default_month))]
                case "/api/order-coverage":
                    result = coverage_payload(app.order_coverage(queries.get("month", app.default_month)))
                case "/api/trace":
                    month = queries.get("month", app.default_month)
                    default_first, default_last = month_window(month)
                    first = date.fromisoformat(queries.get("from", default_first.isoformat()))
                    last = date.fromisoformat(queries.get("to", default_last.isoformat()))
                    if not (date(1901, 1, 1) <= first <= last <= date(2099, 12, 31) and (last - first).days <= 92):
                        raise ValueError("Укажите период до 93 дней, от ранней даты к поздней.")
                    shift = int(queries["shift"]) if "shift" in queries else None
                    if shift not in (None, 1, 2):
                        raise ValueError("Укажите смену 1 или 2.")
                    route = app.trace(month, int(queries.get("row", 0)), queries.get("recipe", "auto"), first, last, shift)
                    result = trace_payload(route, self.server.sources)
                case "/api/source":
                    source = app.source(int(queries.get("file", 0)), queries.get("month", ""), int(queries.get("row", 0)))
                    result = source_payload(source)
                case _:
                    self.send_data(404, {"error": "Такой страницы нет."})
                    return
        except KeyError:
            self.send_data(404, {"error": "Запрошенная строка или лист не найдены."})
            return
        except ValueError as exc:
            self.send_data(400, {"error": str(exc)})
            return
        self.send_data(200, result)
