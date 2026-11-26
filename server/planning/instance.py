"""Validate a fully specified MMKP instance before any solver is called."""

from __future__ import annotations

import math
from collections import Counter


class InputError(ValueError):
    """Incomplete or inconsistent input, distinct from mathematical infeasibility."""


def _object(value, path):
    if not isinstance(value, dict):
        raise InputError(f"{path}: expected object")
    return value


def _string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{path}: expected nonempty string")
    return value


def _number(value, path, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f"{path}: expected finite number")
    if nonnegative and value < 0:
        raise InputError(f"{path}: expected nonnegative number")
    return float(value)


def validate_instance(instance):
    """Return the input unchanged after checking every required option and coefficient."""
    instance = _object(instance, "instance")
    if type(instance.get("schema_version")) is not int or instance["schema_version"] != 1:
        raise InputError("schema_version: expected 1")
    _string(instance.get("instance_id"), "instance_id")
    if instance.get("kind") not in ("synthetic", "scenario", "real"):
        raise InputError("kind: expected synthetic, scenario, or real")
    for key in ("horizon", "score_scale", "consumption_basis", "limits_source", "scores_source"):
        _string(instance.get(key), key)
    components = _object(instance.get("components"), "components")
    if not components:
        raise InputError("components: empty; every resource limit must be explicit")
    for component, limit in components.items():
        _string(component, "components key")
        _number(limit, f"components[{component}]", nonnegative=True)
    orders = instance.get("orders")
    if not isinstance(orders, list) or not orders:
        raise InputError("orders: expected nonempty list")
    order_ids = []
    allowed = {}
    for index, order in enumerate(orders):
        order = _object(order, f"orders[{index}]")
        order_id = _string(order.get("id"), f"orders[{index}].id")
        order_ids.append(order_id)
        versions = order.get("allowed_versions")
        if not isinstance(versions, list) or not versions:
            raise InputError(f"orders[{index}].allowed_versions: expected nonempty list")
        for version in versions:
            _string(version, f"orders[{index}].allowed_versions item")
        if len(set(versions)) != len(versions):
            raise InputError(f"orders[{index}].allowed_versions: duplicate version")
        allowed[order_id] = set(versions)
    if len(set(order_ids)) != len(order_ids):
        raise InputError("orders: duplicate ID")
    options = instance.get("options")
    if not isinstance(options, list):
        raise InputError("options: expected list")
    option_keys = []
    for index, option in enumerate(options):
        option = _object(option, f"options[{index}]")
        order_id = _string(option.get("order_id"), f"options[{index}].order_id")
        version = _string(option.get("version_id"), f"options[{index}].version_id")
        if order_id not in allowed or version not in allowed[order_id]:
            raise InputError(f"options[{index}]: version is not permitted for order")
        option_keys.append((order_id, version))
        _number(option.get("score"), f"options[{index}].score")
        usage = _object(option.get("consumption_tonnes"), f"options[{index}].consumption_tonnes")
        if set(usage) != set(components):
            raise InputError(
                f"options[{index}].consumption_tonnes: expected exactly all components "
                f"(missing={sorted(set(components) - set(usage))}, extra={sorted(set(usage) - set(components))})"
            )
        for component, amount in usage.items():
            _number(amount, f"options[{index}].consumption_tonnes[{component}]", nonnegative=True)
    duplicate_keys = [key for key, count in Counter(option_keys).items() if count != 1]
    if duplicate_keys:
        raise InputError(f"options: duplicate pairs {duplicate_keys[:5]}")
    expected = {(order_id, version) for order_id, versions in allowed.items() for version in versions}
    if set(option_keys) != expected:
        raise InputError(f"options: missing pairs {sorted(expected - set(option_keys))[:5]}")
    return instance
