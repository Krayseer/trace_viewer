"""SciPy/HiGHS MILP for fully specified recipe-selection instances."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .instance import InputError, validate_instance
from .verify import check_plan


def _finite_or_none(value):
    return float(value) if value is not None and math.isfinite(value) else None


def solve(instance, time_limit_seconds=None):
    """Solve a complete instance; never return an unchecked plan as feasible."""
    start = time.perf_counter()
    validate_instance(instance)
    if time_limit_seconds is not None and (
        isinstance(time_limit_seconds, bool)
        or not isinstance(time_limit_seconds, (int, float))
        or not math.isfinite(time_limit_seconds)
        or time_limit_seconds <= 0
    ):
        raise InputError("time_limit_seconds: expected positive finite number")
    order_ids = [order["id"] for order in instance["orders"]]
    components = list(instance["components"])
    option_list = instance["options"]
    order_row = {order_id: index for index, order_id in enumerate(order_ids)}
    component_row = {component: len(order_ids) + index for index, component in enumerate(components)}
    rows = []
    cols = []
    values = []
    for col, option in enumerate(option_list):
        rows.append(order_row[option["order_id"]])
        cols.append(col)
        values.append(1.0)
        for component in components:
            coefficient = float(option["consumption_tonnes"][component])
            if coefficient:
                rows.append(component_row[component])
                cols.append(col)
                values.append(coefficient)
    matrix = coo_matrix(
        (values, (rows, cols)),
        shape=(len(order_ids) + len(components), len(option_list)),
    ).tocsr()
    lower = np.r_[np.ones(len(order_ids)), np.full(len(components), -np.inf)]
    upper = np.r_[np.ones(len(order_ids)), [instance["components"][c] for c in components]]
    prepare_seconds = time.perf_counter() - start
    solver_start = time.perf_counter()
    result = milp(
        c=-np.array([option["score"] for option in option_list], dtype=float),
        integrality=np.ones(len(option_list), dtype=int),
        bounds=Bounds(np.zeros(len(option_list)), np.ones(len(option_list))),
        constraints=LinearConstraint(matrix, lower, upper),
        options={"disp": False, **({"time_limit": float(time_limit_seconds)} if time_limit_seconds else {})},
    )
    solve_seconds = time.perf_counter() - solver_start
    assignments = None
    validation = None
    if result.x is not None:
        if (
            len(result.x) != len(option_list)
            or not np.all(np.isfinite(result.x))
            or np.any(result.x < -1e-7)
            or np.any(result.x > 1 + 1e-7)
            or np.any((result.x > 1e-7) & (result.x < 1 - 1e-7))
        ):
            validation = {"valid": False, "errors": ["solver returned a nonbinary or malformed vector"]}
        else:
            assignments = [
                {"order_id": option["order_id"], "version_id": option["version_id"]}
                for option, value in zip(option_list, result.x)
                if value > 0.5
            ]
            validation = check_plan(instance, assignments, claimed_objective=_finite_or_none(-result.fun if result.fun is not None else None))
            if not validation["valid"]:
                assignments = None
    if validation is not None and not validation["valid"]:
        status = "solver_invalid_plan"
    elif assignments is not None and result.status == 0:
        status = "optimal"
    elif assignments is not None:
        status = "feasible_not_proven_optimal"
    elif result.status == 2:
        status = "proven_infeasible"
    elif result.status == 1:
        status = "no_plan_within_limit"
    else:
        status = "solver_failure"
    bound = _finite_or_none(getattr(result, "mip_dual_bound", None))
    return {
        "instance_id": instance["instance_id"],
        "kind": instance["kind"],
        "status": status,
        "solver": "scipy.optimize.milp/HiGHS",
        "scipy_version": scipy.__version__,
        "python_version": platform.python_version(),
        "solver_status_code": int(result.status),
        "solver_message": str(result.message),
        "orders": len(order_ids),
        "options": len(option_list),
        "components": len(components),
        "time_limit_seconds": time_limit_seconds,
        "prepare_seconds": prepare_seconds,
        "solve_seconds": solve_seconds,
        "total_seconds": time.perf_counter() - start,
        "objective": validation["objective"] if assignments is not None else None,
        "upper_bound": -bound if bound is not None else None,
        "mip_gap": _finite_or_none(getattr(result, "mip_gap", None)),
        "assignments": assignments,
        "independent_validation": validation,
        "input": {
            "horizon": instance["horizon"],
            "score_scale": instance["score_scale"],
            "consumption_basis": instance["consumption_basis"],
            "limits_source": instance["limits_source"],
            "scores_source": instance["scores_source"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time-limit", type=float, default=None)
    args = parser.parse_args()
    raw = args.instance.read_bytes()
    instance = json.loads(raw)
    report = solve(instance, args.time_limit)
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
