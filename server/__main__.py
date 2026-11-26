"""Local browser interface for candidate production links in the project XLS files."""

from __future__ import annotations

import argparse
from pathlib import Path
import webbrowser

from .application import TraceApplication
from .http_api import Handler, TraceServer, WEB_ROOT
from .planning_api import PlanningExamples


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "Данные")
    parser.add_argument("--synthetic-only", action="store_true", help="Run without connecting production workbooks")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser")
    args = parser.parse_args()
    with TraceServer(("127.0.0.1", args.port), Handler) as server:
        server.application = server.sources = None
        workbook_examples = None
        if not args.synthetic_only:
            from .data import XlsDataset

            print(f"Читаю 12 XLS из {args.data}", flush=True)
            dataset = XlsDataset(args.data)
            server.application = TraceApplication(dataset)
            server.sources = dataset
            examples_dir = Path("implementation") / "planner" / "examples"
            workbook_examples = PROJECT_ROOT / examples_dir
            if not workbook_examples.is_dir():
                workbook_examples = args.data.resolve().parent / examples_dir
        server.planning_examples = PlanningExamples(WEB_ROOT / "planning_examples", workbook_examples)
        url = f"http://127.0.0.1:{server.server_port}/"
        if args.synthetic_only:
            url += "?view=comparison"
        print(f"Маршрут заказа: {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
