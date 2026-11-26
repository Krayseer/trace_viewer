"""HTTP request handling and static assets for the local trace viewer."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import traceback
from urllib.parse import parse_qs, urlsplit

from .api import api_response
from .application import TraceApplication
from .planning_api import MAX_REQUEST_BYTES, PlanningExamples, solve_request
from .presentation import StageSources


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
PLANNING_EXAMPLES = "/api/planning/examples"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/viewer.css": ("viewer.css", "text/css"),
    "/viewer.js": ("viewer.js", "text/javascript"),
    "/viewer_ui.js": ("viewer_ui.js", "text/javascript"),
    "/viewer_table.js": ("viewer_table.js", "text/javascript"),
    "/viewer_orders_panel.js": ("viewer_orders_panel.js", "text/javascript"),
    "/viewer_planning.js": ("viewer_planning.js", "text/javascript"),
    "/fonts/roboto-cyrillic-wght-normal.woff2": ("fonts/roboto-cyrillic-wght-normal.woff2", "font/woff2"),
    "/fonts/roboto-latin-wght-normal.woff2": ("fonts/roboto-latin-wght-normal.woff2", "font/woff2"),
}


class TraceServer(ThreadingHTTPServer):
    application: TraceApplication
    sources: StageSources
    planning_examples: PlanningExamples


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
        if url.path == PLANNING_EXAMPLES:
            self.send_data(200, {"examples": self.server.planning_examples.names()})
            return
        if url.path.startswith(PLANNING_EXAMPLES + "/"):
            example = self.server.planning_examples.read(url.path.removeprefix(PLANNING_EXAMPLES + "/"))
            if example is None:
                self.send_data(404, {"error": "Пример расчёта недоступен."})
            else:
                self.send_data(200, example)
            return
        queries = {key: vals[0] for key, vals in parse_qs(url.query).items()}
        self.send_data(*api_response(self.server.application, self.server.sources, url.path, queries))

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/planning/solve":
            self.send_data(404, {"error": "Такой страницы нет."})
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            size = -1
        if not 0 <= size <= MAX_REQUEST_BYTES:
            self.send_data(413, {"error": "Размер запроса должен быть указан и составлять не более 100 МиБ."})
            return
        try:
            self.send_data(*solve_request(self.rfile.read(size)))
        except ModuleNotFoundError:
            self.send_data(503, {"error": "Для расчёта в окружении сервера нужны NumPy и SciPy."})
        except Exception:
            traceback.print_exc()
            self.send_data(500, {"error": "Ошибка решателя. Проверьте вход и повторите расчёт."})
