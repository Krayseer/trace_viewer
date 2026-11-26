"""Direct plan verification independent of the MILP matrix and solver output."""

from __future__ import annotations

import math

from .instance import validate_instance


ABS_TOL_TONNES = 1e-7
REL_TOL_TONNES = 1e-8


def check_plan(instance, assignments, claimed_objective=None):
    """Recalculate one assignment per source order, consumption, and objective.

    `assignments` is a list of {order_id, version_id}. No result.x or matrix is used.
    Invalid plans return diagnostics rather than a silently repaired plan.
    """
    validate_instance(instance)
    errors = []
    if not isinstance(assignments, list):
        assignments = []
        errors.append("assignments: expected list")
    ordered_ids = [order["id"] for order in instance["orders"]]
    allowed = {order["id"]: set(order["allowed_versions"]) for order in instance["orders"]}
    options = {(o["order_id"], o["version_id"]): o for o in instance["options"]}
    chosen = {}
    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            errors.append(f"assignments[{index}]: expected object")
            continue
        order_id = assignment.get("order_id")
        version = assignment.get("version_id")
        if not isinstance(order_id, str) or not isinstance(version, str):
            errors.append(f"assignments[{index}]: expected string order_id and version_id")
            continue
        if order_id not in allowed:
            errors.append(f"assignments[{index}]: unknown order {order_id!r}")
            continue
        if order_id in chosen:
            errors.append(f"assignments[{index}]: duplicate order {order_id!r}")
            continue
        if version not in allowed[order_id]:
            errors.append(f"assignments[{index}]: forbidden version {version!r} for {order_id!r}")
            continue
        chosen[order_id] = version
    missing = [order_id for order_id in ordered_ids if order_id not in chosen]
    if missing:
        errors.append(f"missing orders: {missing}")
    used = {component: 0.0 for component in instance["components"]}
    objective = 0.0
    for order_id in ordered_ids:
        if order_id not in chosen:
            continue
        option = options[(order_id, chosen[order_id])]
        objective += float(option["score"])
        for component in used:
            used[component] += float(option["consumption_tonnes"][component])
    resource_report = {}
    for component, limit in instance["components"].items():
        limit = float(limit)
        slack = limit - used[component]
        tolerance = ABS_TOL_TONNES + REL_TOL_TONNES * max(1.0, abs(limit))
        if slack < -tolerance:
            errors.append(f"component {component!r} exceeded by {-slack:.12g} tonnes")
        resource_report[component] = {
            "used_tonnes": used[component],
            "limit_tonnes": limit,
            "slack_tonnes": slack,
            "tolerance_tonnes": tolerance,
        }
    if claimed_objective is not None:
        if isinstance(claimed_objective, bool) or not isinstance(claimed_objective, (int, float)) or not math.isfinite(claimed_objective):
            errors.append("claimed objective is not finite")
        elif abs(float(claimed_objective) - objective) > 1e-7 + 1e-8 * max(1.0, abs(objective)):
            errors.append("claimed objective differs from direct recalculation")
    return {
        "valid": not errors,
        "errors": errors,
        "assigned_orders": len(chosen),
        "original_orders": len(ordered_ids),
        "objective": objective,
        "resources": resource_report,
    }
