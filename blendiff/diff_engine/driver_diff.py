from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.driver_diff import DriverDiff


def _driver_key(driver: dict) -> tuple:
    return (driver["data_path"], driver["array_index"])


def _variables_equal(vars_a: list[dict], vars_b: list[dict]) -> bool:
    """Deep equality check for driver variable lists."""
    if len(vars_a) != len(vars_b):
        return False
    for va, vb in zip(vars_a, vars_b):
        if va.get("name") != vb.get("name"):
            return False
        if va.get("type") != vb.get("type"):
            return False
        targets_a = va.get("targets", [])
        targets_b = vb.get("targets", [])
        if len(targets_a) != len(targets_b):
            return False
        for ta, tb in zip(targets_a, targets_b):
            if ta != tb:
                return False
    return True


def diff_drivers(
    obj_name: str,
    drivers_a: list[dict],
    drivers_b: list[dict],
    prefix: str = "drivers",
) -> DriverDiff:

    changes: list[PropertyChange] = []

    map_a = {_driver_key(d): d for d in drivers_a}
    map_b = {_driver_key(d): d for d in drivers_b}
    all_keys = sorted(set(map_a) | set(map_b))

    for key in all_keys:
        data_path, array_index = key
        slot = f"{prefix}[{data_path}][{array_index}]"

        drv_a = map_a.get(key)
        drv_b = map_b.get(key)

        if drv_a is None:
            changes.append(PropertyChange(slot, None, drv_b["driver_type"]))
            continue

        if drv_b is None:
            changes.append(PropertyChange(slot, drv_a["driver_type"], None))
            continue

        # Driver type changed
        if drv_a["driver_type"] != drv_b["driver_type"]:
            changes.append(PropertyChange(
                f"{slot}.driver_type",
                drv_a["driver_type"],
                drv_b["driver_type"],
            ))

        # Expression changed (SCRIPTED drivers)
        if drv_a["expression"] != drv_b["expression"]:
            changes.append(PropertyChange(
                f"{slot}.expression",
                drv_a["expression"],
                drv_b["expression"],
            ))

        # use_self changed
        if drv_a["use_self"] != drv_b["use_self"]:
            changes.append(PropertyChange(
                f"{slot}.use_self",
                drv_a["use_self"],
                drv_b["use_self"],
            ))

        # Variables changed
        if not _variables_equal(drv_a["variables"], drv_b["variables"]):
            changes.append(PropertyChange(
                f"{slot}.variables",
                [v["name"] for v in drv_a["variables"]],
                [v["name"] for v in drv_b["variables"]],
            ))

    return DriverDiff(object_name=obj_name, changes=changes)


def diff_all_drivers(
    objs_a: dict[str, dict],
    objs_b: dict[str, dict],
) -> list[DriverDiff]:

    results: list[DriverDiff] = []

    for name in sorted(set(objs_a) & set(objs_b)):
        diff = diff_drivers(
            obj_name=name,
            drivers_a=objs_a[name].get("drivers", []),
            drivers_b=objs_b[name].get("drivers", []),
        )
        if diff.changes:
            results.append(diff)

    return results