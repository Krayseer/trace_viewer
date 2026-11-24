"""Local browser interface for candidate production links in the project XLS files."""

from __future__ import annotations

import argparse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .data import Dataset, month_window


HERE = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html"),
    "/viewer.css": ("viewer.css", "text/css"),
    "/viewer.js": ("viewer.js", "text/javascript"),
    "/fonts/roboto-cyrillic-wght-normal.woff2": ("fonts/roboto-cyrillic-wght-normal.woff2", "font/woff2"),
    "/fonts/roboto-latin-wght-normal.woff2": ("fonts/roboto-latin-wght-normal.woff2", "font/woff2"),
}


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status, body, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime if mime.startswith("font/") else f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_data(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_body(status, body, "application/json")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in ASSETS:
            filename, mime = ASSETS[url.path]
            self.send_body(200, (HERE / filename).read_bytes(), mime)
            return
        queries = {key: vals[0] for key, vals in parse_qs(url.query).items()}
        data = self.server.data
        try:
            match url.path:
                case "/api/months":
                    result = [{"id": m, "label": data.sheets[1, m]} for m in data.months]
                case "/api/orders":
                    result = data.orders(queries.get("month", data.months[0]))
                case "/api/order-coverage":
                    result = data.order_coverage(queries.get("month", data.months[0]))
                case "/api/trace":
                    month = queries.get("month", data.months[0])
                    default_first, default_last = month_window(month)
                    first = date.fromisoformat(queries.get("from", default_first.isoformat()))
                    last = date.fromisoformat(queries.get("to", default_last.isoformat()))
                    if not (date(1901, 1, 1) <= first <= last <= date(2099, 12, 31) and (last - first).days <= 92):
                        raise ValueError("Укажите период до 93 дней, от ранней даты к поздней.")
                    shift = int(queries["shift"]) if "shift" in queries else None
                    if shift not in (None, 1, 2):
                        raise ValueError("Укажите смену 1 или 2.")
                    result = data.trace(month, int(queries.get("row", 0)), queries.get("recipe", "auto"), first, last, shift)
                case "/api/source":
                    result = data.source(int(queries.get("file", 0)), queries.get("month", ""), int(queries.get("row", 0)))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE.parents[1] / "Данные")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Читаю 12 XLS из {args.data}", flush=True)
        server.data = Dataset(args.data)
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Маршрут заказа: {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
