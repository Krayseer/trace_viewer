"""Export a static GitHub Pages demo using the production trace rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from .application import TraceApplication, month_window
from .data import XlsDataset
from .demo_books import write_demo_books
from .presentation import coverage_payload, order_payload, source_payload, trace_payload


def write_json(path: Path, value: list | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")


def export_data(directory: Path, dataset: XlsDataset) -> None:
    app = TraceApplication(dataset)
    months = app.months()
    write_json(directory / "months.json", [{"id": month, "label": name} for month, name in months])
    source_rows: set[tuple[int, str, int]] = set()

    for month, _ in months:
        month_directory = directory / month
        orders = app.orders(month)
        write_json(month_directory / "orders.json", [order_payload(order) for order in orders])
        write_json(month_directory / "coverage.json", coverage_payload(app.order_coverage(month)))
        first, last = month_window(month)
        for order in orders:
            number = order.source.row
            automatic = app.trace(month, number, "auto", first, last, None)
            recipes = ["auto", "all", *(version.id for version in automatic.versions)]
            by_shift: dict[str, dict[str, dict]] = {}
            for shift in (None, 1, 2):
                variants = by_shift["all" if shift is None else str(shift)] = {}
                for recipe in recipes:
                    trace = app.trace(month, number, recipe, first, last, shift)
                    payload = variants[recipe] = trace_payload(trace, dataset)
                    source_rows.update(
                        (stage["file"], row["month"], row["row"])
                        for stage in payload["stages"] for row in stage["rows"]
                    )
                    source_rows.update(
                        (link["file"], link["month"], link["row"])
                        for gap in payload["gaps"] for link in gap["links"]
                    )
            write_json(month_directory / "traces" / f"{number}.json", by_shift)

    for file, month, number in sorted(source_rows):
        path = directory / "sources" / str(file) / month / f"{number}.json"
        write_json(path, source_payload(app.source(file, month, number)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for the static site")
    output = parser.parse_args().output
    web = Path(__file__).resolve().parents[1] / "web"
    shutil.copytree(web, output)
    index = output / "index.html"
    html = index.read_text(encoding="utf-8")
    if 'data-source="api"' not in html:
        raise ValueError("Static demo mode marker missing from index.html")
    index.write_text(html.replace('data-source="api"', 'data-source="static"', 1), encoding="utf-8")
    with TemporaryDirectory() as books:
        directory = Path(books)
        write_demo_books(directory)
        export_data(output / "data", XlsDataset(directory))


if __name__ == "__main__":
    main()
