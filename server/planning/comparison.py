"""Run the three project methods sequentially on one planning instance."""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

import highspy
import numpy as np
from scipy.sparse import coo_matrix

from .fast import solve as fast_solve
from .instance import validate_instance
from .verify import check_plan


RUN_LOCK = Lock()


def _finite(value):
    return float(value) if math.isfinite(value) else None


def _run_highs(instance, budget, log_path, *, warm):
    started = time.perf_counter()
    method = "warm" if warm else "cold"
    first_event = None
    initial = None
    if warm:
        initial = fast_solve(instance, deadline=started + min(20.0, budget / 3))
        if initial["assignments"] is None:
            return {
                "method": method, "status": "no_warm_start",
                "seconds": time.perf_counter() - started,
            }

    orders = instance["orders"]
    options = instance["options"]
    components = instance["components"]
    order_rows = {order["id"]: index for index, order in enumerate(orders)}
    component_rows = {key: index for index, key in enumerate(components, len(orders))}
    rows, columns, values = [], [], []
    for column, option in enumerate(options):
        rows.append(order_rows[option["order_id"]])
        columns.append(column)
        values.append(1.0)
        for component, amount in option["consumption_tonnes"].items():
            if amount:
                rows.append(component_rows[component])
                columns.append(column)
                values.append(amount)

    matrix = coo_matrix(
        (values, (rows, columns)), shape=(len(orders) + len(components), len(options)),
    ).tocsc()
    model = highspy.HighsLp()
    model.num_col_, model.num_row_ = len(options), matrix.shape[0]
    model.col_cost_ = -np.array([option["score"] for option in options], dtype=float)
    model.col_lower_, model.col_upper_ = np.zeros(len(options)), np.ones(len(options))
    model.row_lower_ = np.r_[np.ones(len(orders)), np.full(len(components), -highspy.kHighsInf)]
    model.row_upper_ = np.r_[np.ones(len(orders)), list(components.values())]
    model.integrality_ = [highspy.HighsVarType.kInteger] * len(options)
    model.a_matrix_.start_ = matrix.indptr.astype(np.int32)
    model.a_matrix_.index_ = matrix.indices.astype(np.int32)
    model.a_matrix_.value_ = matrix.data

    solver = highspy.Highs()
    ok = highspy.HighsStatus.kOk

    def require_ok(status):
        if status != ok:
            raise RuntimeError(f"HiGHS rejected comparison setup: {status}")

    for key, value in (("log_to_console", False), ("threads", 1), ("random_seed", 0)):
        require_ok(solver.setOptionValue(key, value))
    require_ok(solver.passModel(model))

    def on_event(event, _message, _data, _input, _userdata):
        nonlocal first_event
        if event == highspy.cb.kCallbackMipSolution and first_event is None:
            first_event = time.perf_counter() - started

    require_ok(solver.setCallback(on_event, None))
    require_ok(solver.startCallback(highspy.cb.kCallbackMipSolution))
    if initial is not None:
        option_columns = {(option["order_id"], option["version_id"]): i for i, option in enumerate(options)}
        vector = np.zeros(len(options))
        for assignment in initial["assignments"]:
            vector[option_columns[assignment["order_id"], assignment["version_id"]]] = 1
        solution = highspy.HighsSolution()
        solution.col_value = vector
        solution.value_valid = True
        require_ok(solver.setSolution(solution))

    # Leave time for final verification within the shared per-method budget.
    require_ok(solver.setOptionValue("log_file", str(log_path)))
    try:
        remaining = budget - (time.perf_counter() - started)
        if remaining <= 0:
            return {"method": method, "status": "no_plan_within_limit", "seconds": time.perf_counter() - started}
        require_ok(solver.setOptionValue("time_limit", min(remaining, max(0.01, remaining - 4.0))))
        solver.run()
    finally:
        solver.setOptionValue("log_file", "")
    start_accepted = None
    if initial is not None:
        log = log_path.read_text(encoding="utf-8", errors="replace")
        objectives = re.findall(r"MIP start solution is feasible, objective value is\s+(\S+)", log)
        start_accepted = any(
            math.isclose(-float(value), initial["objective"], rel_tol=0, abs_tol=1e-5)
            for value in objectives
        )
    model_status = solver.getModelStatus()
    solution = solver.getSolution()
    info = solver.getInfo()
    plan = None
    check = None
    if solution.value_valid:
        vector = np.asarray(solution.col_value)
        if len(vector) == len(options) and np.all(np.isfinite(vector)) and np.all(
            (np.abs(vector) <= 1e-6) | (np.abs(vector - 1) <= 1e-6),
        ):
            candidate = [
                {"order_id": option["order_id"], "version_id": option["version_id"]}
                for option, value in zip(options, vector) if value > 0.5
            ]
            check = check_plan(instance, candidate)
            if check["valid"]:
                plan = candidate

    if plan is not None:
        status = "optimal" if model_status == highspy.HighsModelStatus.kOptimal else "feasible_not_proven_optimal"
    elif model_status == highspy.HighsModelStatus.kInfeasible:
        status = "proven_infeasible"
    elif check is not None:
        status = "invalid_plan"
    else:
        status = "no_valid_plan_from_solver"

    return {
        "method": method,
        "status": status,
        "seconds": time.perf_counter() - started,
        "first_solver_event_seconds": first_event,
        "first_verified_seconds": (
            initial["first_feasible_seconds_after_load"] if initial is not None else None
        ),
        "start_accepted": start_accepted,
        "objective": check["objective"] if plan is not None else None,
        "gap": _finite(info.mip_gap) if plan is not None else None,
        "upper_bound": _finite(-info.mip_dual_bound) if plan is not None else None,
        "assigned": len(plan) if plan is not None else None,
        "plan": plan,
        "resources": check["resources"] if plan is not None else None,
    }


def compare(instance, budget):
    validate_instance(instance)
    started = time.perf_counter()
    fast = fast_solve(instance, deadline=started + budget)
    check = fast["independent_validation"]
    methods = [{
        "method": "fast",
        "status": fast["status"],
        "seconds": time.perf_counter() - started,
        "first_verified_seconds": fast["first_feasible_seconds_after_load"],
        "objective": fast["objective"],
        "assigned": check["assigned_orders"] if check else None,
        "plan": fast["assignments"],
        "resources": check["resources"] if check else None,
        "repair_moves": fast["repair_moves"],
        "improvement_moves": fast["improvement_moves"],
    }]
    with TemporaryDirectory(prefix="shihta-highs-") as directory:
        methods.extend(
            _run_highs(instance, budget, Path(directory) / f"{method}.log", warm=method == "warm")
            for method in ("cold", "warm")
        )
    return {
        "origin": "live",
        "id": instance["instance_id"],
        "kind": instance["kind"],
        "orders": len(instance["orders"]),
        "options": len(instance["options"]),
        "components": len(instance["components"]),
        "budget": budget,
        "methods": methods,
    }
