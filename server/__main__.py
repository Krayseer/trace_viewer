"""Local browser interface for candidate production links in the project XLS files."""

from __future__ import annotations

import argparse
from pathlib import Path
import webbrowser

from .application import TraceApplication
from .data import XlsDataset
from .http_api import Handler, TraceServer, WEB_ROOT
from .planning_api import PlanningExamples


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "Данные")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser")
    args = parser.parse_args()
    with TraceServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Читаю 12 XLS из {args.data}", flush=True)
        dataset = XlsDataset(args.data)
        server.application = TraceApplication(dataset)
        server.sources = dataset
        server.planning_examples = PlanningExamples(
            WEB_ROOT / "planning_examples", PROJECT_ROOT / "implementation" / "planner" / "examples",
        )
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
