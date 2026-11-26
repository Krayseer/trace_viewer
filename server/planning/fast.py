"""Greedy score selection, violation repair, and feasible one-order improvement.

This is a heuristic: failure to find a plan is not proof of infeasibility.
Every reported feasible plan is independently checked by verify.check_plan.
"""

from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

from .instance import validate_instance
from .verify import ABS_TOL_TONNES, REL_TOL_TONNES, check_plan


def solve(instance, *, deadline):
    start = time.perf_counter()
    validate_instance(instance)
    order_ids = [order["id"] for order in instance["orders"]]
    components = list(instance["components"])
    limits = np.array([instance["components"][key] for key in components], dtype=float)
    tolerance = ABS_TOL_TONNES + REL_TOL_TONNES * np.maximum(1.0, np.abs(limits))
    denominator = np.maximum(limits, 1.0)
    options = instance["options"]
    by_order = defaultdict(list)
    for index, option in enumerate(options):
        by_order[option["order_id"]].append(index)
    groups = [np.array(by_order[order_id], dtype=int) for order_id in order_ids]
    scores = np.array([option["score"] for option in options], dtype=float)
    usage = np.array(
        [[option["consumption_tonnes"][component] for component in components] for option in options],
        dtype=float,
    )
    chosen = np.array([group[np.argmax(scores[group])] for group in groups], dtype=int)
    used = usage[chosen].sum(axis=0)
    prepared_at = time.perf_counter()

    def assignments():
        return [
            {"order_id": order_id, "version_id": options[int(index)]["version_id"]}
            for order_id, index in zip(order_ids, chosen)
        ]

    def violation(values):
        return np.maximum((values - limits - tolerance) / denominator, 0.0).sum(axis=-1)

    repair_moves = 0
    first_plan = None
    first_check = None
    first_feasible_seconds = None
    reason = None
    while True:
        if not np.any(used > limits + tolerance):
            candidate = assignments()
            check = check_plan(instance, candidate, claimed_objective=float(scores[chosen].sum()))
            if check["valid"]:
                first_plan, first_check = candidate, check
                first_feasible_seconds = time.perf_counter() - start
            else:
                reason = "independent_validation_failed"
            break
        if time.perf_counter() >= deadline:
            reason = "budget_exhausted_before_feasible_plan"
            break
        current_violation = float(violation(used))
        best = None
        for order_number, group in enumerate(groups):
            if time.perf_counter() >= deadline:
                reason = "budget_exhausted_before_feasible_plan"
                break
            candidate_used = used - usage[chosen[order_number]] + usage[group]
            penalties = violation(candidate_used)
            minimum = float(np.min(penalties))
            tied = np.flatnonzero(penalties <= minimum + 1e-12)
            candidate_index = int(group[tied[np.argmax(scores[group[tied]])]])
            reduction = current_violation - minimum
            gain = float(scores[candidate_index] - scores[chosen[order_number]])
            if best is None or reduction > best[0] + 1e-12 or (
                abs(reduction - best[0]) <= 1e-12 and gain > best[1] + 1e-12
            ):
                best = (reduction, gain, order_number, candidate_index)
        if reason is not None:
            break
        if best is None or best[0] <= 1e-12:
            reason = "repair_stalled_without_feasible_plan"
            break
        _, _, order_number, candidate_index = best
        used += usage[candidate_index] - usage[chosen[order_number]]
        chosen[order_number] = candidate_index
        repair_moves += 1

    improvements = 0
    if first_plan is not None:
        while time.perf_counter() < deadline:
            best = None
            for order_number, group in enumerate(groups):
                if time.perf_counter() >= deadline:
                    break
                candidates = group[scores[group] > scores[chosen[order_number]] + 1e-12]
                if not len(candidates):
                    continue
                feasible = np.all(
                    used - usage[chosen[order_number]] + usage[candidates] <= limits + tolerance,
                    axis=1,
                )
                if not np.any(feasible):
                    continue
                candidate_index = int(candidates[feasible][np.argmax(scores[candidates[feasible]])])
                gain = float(scores[candidate_index] - scores[chosen[order_number]])
                if best is None or gain > best[0] + 1e-12:
                    best = (gain, order_number, candidate_index)
            if best is None:
                break
            _, order_number, candidate_index = best
            used += usage[candidate_index] - usage[chosen[order_number]]
            chosen[order_number] = candidate_index
            improvements += 1

    final_plan = assignments() if first_plan is not None else None
    final_check = (
        check_plan(instance, final_plan, claimed_objective=float(scores[chosen].sum()))
        if final_plan is not None else None
    )
    if final_check is not None and not final_check["valid"]:
        # The last verified plan remains a valid result even if improvement fails.
        final_plan, final_check = first_plan, first_check
        reason = "improvement_validation_failed; returning_first_feasible_plan"
    return {
        "instance_id": instance["instance_id"],
        "kind": instance["kind"],
        "method": "deterministic_greedy_violation_repair_single_order_improvement",
        "status": "feasible_not_proven_optimal" if final_plan is not None else "no_plan_within_limit",
        "reason": reason,
        "orders": len(order_ids),
        "options": len(options),
        "components": len(components),
        "prepare_seconds": prepared_at - start,
        "first_feasible_seconds_after_load": first_feasible_seconds,
        "method_seconds_after_load": time.perf_counter() - start,
        "repair_moves": repair_moves,
        "improvement_moves": improvements,
        "first_feasible_objective": first_check["objective"] if first_check else None,
        "objective": final_check["objective"] if final_check else None,
        "upper_bound": None,
        "gap": None,
        "first_feasible_assignments": first_plan,
        "assignments": final_plan,
        "first_feasible_validation": first_check,
        "independent_validation": final_check,
    }
