"""Local browser interface for candidate production links in the project XLS files."""

from __future__ import annotations

import argparse
from pathlib import Path
import webbrowser

from .application import TraceApplication
from .data import XlsDataset
from .http_api import Handler, TraceServer


HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE.parents[1] / "Данные")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser")
    args = parser.parse_args()
    with TraceServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Читаю 12 XLS из {args.data}", flush=True)
        dataset = XlsDataset(args.data)
        server.application = TraceApplication(dataset)
        server.sources = dataset
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
