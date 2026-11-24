"""Application operations shared by the HTTP server and the browser."""

from datetime import date

from .application import TraceApplication, month_window
from .presentation import StageSources, coverage_payload, order_payload, source_payload, trace_payload


def api_response(
    app: TraceApplication, sources: StageSources, path: str, queries: dict[str, str],
) -> tuple[int, list | dict]:
    try:
        match path:
            case "/api/months":
                result = [{"id": month, "label": label} for month, label in app.months()]
            case "/api/orders":
                month = queries.get("month", app.default_month)
                result = [order_payload(order) for order in app.orders(month)]
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
                result = trace_payload(route, sources)
            case "/api/source":
                source = app.source(int(queries.get("file", 0)), queries.get("month", ""), int(queries.get("row", 0)))
                result = source_payload(source)
            case _:
                return 404, {"error": "Такой страницы нет."}
    except KeyError:
        return 404, {"error": "Запрошенная строка или лист не найдены."}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, result
