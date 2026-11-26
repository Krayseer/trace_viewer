"""Validate edited assumptions, solve, and prepare a truthful display payload."""

from __future__ import annotations

import copy
import math

from .instance import InputError, validate_instance
from .solve import solve
from .verify import check_plan


def _positive(value, label, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f"{label}: expected finite number")
    if value < 0 or (value == 0 and not allow_zero):
        raise InputError(f"{label}: expected {'nonnegative' if allow_zero else 'positive'} number")
    return float(value)


def _overrides(raw, expected, label, allow_zero):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InputError(f"{label}: expected object")
    unknown = set(raw) - set(expected)
    if unknown:
        raise InputError(f"{label}: unknown IDs {sorted(unknown)[:5]}")
    return {key: _positive(value, f"{label}[{key}]", allow_zero) for key, value in raw.items()}


def prepare_instance(source, volume_overrides=None, limit_overrides=None):
    """Scale explicit baseline options; never infer a missing volume or limit."""
    validate_instance(source)
    if source["kind"] not in ("synthetic", "scenario"):
        raise InputError("planner accepts only synthetic or scenario input")
    if source.get("volume_scaling") != "linear_from_baseline":
        raise InputError("volume_scaling: expected linear_from_baseline")
    if not isinstance(source.get("volume_source"), str) or not source["volume_source"].strip():
        raise InputError("volume_source: expected nonempty string")
    sources = source.get("component_sources")
    if not isinstance(sources, dict) or set(sources) != set(source["components"]):
        raise InputError("component_sources: expected one source for every component")
    for component, description in sources.items():
        if not isinstance(description, str) or not description.strip():
            raise InputError(f"component_sources[{component}]: expected nonempty string")
    base_volumes = {}
    for order in source["orders"]:
        base_volumes[order["id"]] = _positive(order.get("volume_tonnes"), f"orders[{order['id']}].volume_tonnes")
    volumes = _overrides(volume_overrides, base_volumes, "volume_overrides_tonnes", False)
    limits = _overrides(limit_overrides, source["components"], "limit_overrides_tonnes", True)
    instance = copy.deepcopy(source)
    for order in instance["orders"]:
        order["volume_tonnes"] = volumes.get(order["id"], base_volumes[order["id"]])
    for option in instance["options"]:
        factor = volumes.get(option["order_id"], base_volumes[option["order_id"]]) / base_volumes[option["order_id"]]
        option["score"] *= factor
        option["consumption_tonnes"] = {c: amount * factor for c, amount in option["consumption_tonnes"].items()}
    instance["components"].update(limits)
    validate_instance(instance)
    return instance


def plan(source, volume_overrides=None, limit_overrides=None, time_limit_seconds=30):
    _positive(time_limit_seconds, "time_limit_seconds")
    instance = prepare_instance(source, volume_overrides, limit_overrides)
    report = solve(instance, time_limit_seconds=time_limit_seconds)
    assignments = report["assignments"]
    validation = check_plan(instance, assignments, report["objective"]) if assignments is not None else None
    if assignments is not None and (not validation["valid"] or validation != report["independent_validation"]):
        raise RuntimeError("display plan differs from independent core validation")
    chosen = {a["order_id"]: a["version_id"] for a in assignments or []}
    options = {(o["order_id"], o["version_id"]): o for o in instance["options"]}
    displayed_plan = [
        {
            "order_id": order["id"],
            "version_id": chosen[order["id"]],
            "volume_tonnes": order["volume_tonnes"],
            "score": options[(order["id"], chosen[order["id"]])]["score"],
        }
        for order in instance["orders"]
    ] if assignments is not None else None
    resources = []
    for component, limit in instance["components"].items():
        resource = validation["resources"][component] if validation else None
        slack = resource["slack_tonnes"] if resource else None
        tol = resource["tolerance_tonnes"] if resource else None
        edited_limit = bool(limit_overrides and component in limit_overrides)
        original_source = instance["component_sources"][component]
        resources.append({
            "component": component,
            "limit_tonnes": limit,
            "source": f"Сценарная правка пользователя; исходный лимит: {original_source}" if edited_limit else original_source,
            "edited": edited_limit,
            "used_tonnes": resource["used_tonnes"] if resource else None,
            "slack_tonnes": slack,
            "utilization": resource["used_tonnes"] / limit if resource and limit > 0 else None,
            "bottleneck": bool(resource and limit > 0 and slack <= max(tol, 0.05 * limit)),
        })
    return {
        "instance_id": instance["instance_id"],
        "kind": instance["kind"],
        "assumptions": {
            "horizon": instance["horizon"],
            "consumption_basis": instance["consumption_basis"],
            "volume_source": instance["volume_source"],
            "volume_scaling": "linear_from_baseline: option score and consumption scale in proportion to edited order volume",
            "score_scale": instance["score_scale"],
            "scores_source": instance["scores_source"],
            "limits_source": instance["limits_source"],
            "edited_limits": "User-supplied scenario overrides" if limit_overrides else None,
            "edited_volumes": "User-supplied scenario overrides" if volume_overrides else None,
        },
        "status": report["status"],
        "solver_message": report["solver_message"],
        "objective": report["objective"],
        "upper_bound": report["upper_bound"],
        "mip_gap": report["mip_gap"],
        "total_seconds": report["total_seconds"],
        "orders": [{"id": o["id"], "volume_tonnes": o["volume_tonnes"], "edited": bool(volume_overrides and o["id"] in volume_overrides)} for o in instance["orders"]],
        "plan": displayed_plan,
        "resources": resources,
        "independent_validation": validation,
    }
