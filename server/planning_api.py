"""Scenario input and result contract for HTTP and browser workers."""

from __future__ import annotations

import json
from pathlib import Path

from .planning.instance import InputError


PUBLIC_EXAMPLES = ("synthetic_small", "synthetic_infeasible")
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


class PlanningExamples:
    def __init__(self, public: Path, workbook: Path):
        self.paths = {
            name: folder / f"{name}.json"
            for names, folder in ((PUBLIC_EXAMPLES, public), (WORKBOOK_EXAMPLES, workbook))
            for name in names
        }

    def names(self) -> list[str]:
        return [name for name, path in self.paths.items() if path.is_file()]

    def read(self, name: str) -> dict | None:
        path = self.paths.get(name)
        return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None
