"""Scenario input and result contract for HTTP and browser workers."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .planning.instance import InputError


PUBLIC_EXAMPLES = ("synthetic_small", "synthetic_infeasible")
COMPARISON_EXAMPLE = "synthetic_comparison"
WORKBOOK_EXAMPLES = ("march_subset_scenario", "may_integration_scenario")
MAX_REQUEST_BYTES = 100 * 1024 * 1024


def solve_request(body: str | bytes) -> tuple[int, dict]:
    try:
        request = json.loads(body)
        if not isinstance(request, dict) or not isinstance(request.get("instance"), dict):
            raise InputError("Передайте полный сценарий в поле instance.")
        from .planning.service import plan

        result = plan(
            request["instance"],
            request.get("volume_overrides_tonnes"),
            request.get("limit_overrides_tonnes"),
            request.get("time_limit_seconds", 30),
        )
        return 200, result
    except (InputError, ValueError, TypeError, OverflowError) as error:
        return 422, {"status": "invalid_input", "error": str(error)}


def solve_json(body: str) -> str:
    return json.dumps(solve_request(body), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def compare_request(body: bytes) -> tuple[int, dict]:
    try:
        request = json.loads(body)
        if not isinstance(request, dict) or not isinstance(request.get("instance"), dict):
            raise InputError("Передайте полный сценарий в поле instance.")
        budget = request.get("budget", 15)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or not 6 <= budget <= 120:
            raise InputError("Задайте от 6 до 120 секунд на метод.")

        from .planning.comparison import RUN_LOCK, compare

        if not RUN_LOCK.acquire(blocking=False):
            return 409, {"error": "Сравнение уже выполняется. Дождитесь его завершения."}
        try:
            return 200, compare(request["instance"], budget)
        finally:
            RUN_LOCK.release()
    except ModuleNotFoundError:
        return 503, {"error": "Для локального сравнения установите NumPy, SciPy и highspy==1.12.0."}
    except (InputError, ValueError, TypeError, OverflowError) as error:
        return 422, {"error": str(error)}


class PlanningExamples:
    def __init__(self, public: Path, workbook: Path | None):
        self.paths = {name: public / f"{name}.json" for name in PUBLIC_EXAMPLES}
        if workbook is not None:
            self.paths.update({name: workbook / f"{name}.json" for name in WORKBOOK_EXAMPLES})
        self.comparison_path = public / f"{COMPARISON_EXAMPLE}.json"

    def names(self) -> list[str]:
        return [name for name, path in self.paths.items() if path.is_file()]

    def read(self, name: str) -> dict | None:
        path = self.comparison_path if name == COMPARISON_EXAMPLE else self.paths.get(name)
        return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None
