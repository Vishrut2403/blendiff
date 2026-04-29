from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.fcurve_diff import FCurveDiff

_FLOAT_EPSILON = 1e-3


def _frames_equal(a: float, b: float) -> bool:
    return abs(a - b) < _FLOAT_EPSILON


def _curve_key(curve: dict) -> tuple:
    return (curve["data_path"], curve["array_index"])


def diff_fcurves(
    obj_name: str,
    curves_a: list[dict],
    curves_b: list[dict],
    prefix: str = "fcurves",
) -> FCurveDiff:

    changes: list[PropertyChange] = []

    map_a = {_curve_key(c): c for c in curves_a}
    map_b = {_curve_key(c): c for c in curves_b}

    all_keys = sorted(set(map_a) | set(map_b))

    for key in all_keys:
        data_path, array_index = key
        slot = f"{prefix}[{data_path}][{array_index}]"

        curve_a = map_a.get(key)
        curve_b = map_b.get(key)

        if curve_a is None:
            changes.append(PropertyChange(slot, None, curve_b["keyframe_count"]))
            continue

        if curve_b is None:
            changes.append(PropertyChange(slot, curve_a["keyframe_count"], None))
            continue

        # Compare per-property
        if curve_a["keyframe_count"] != curve_b["keyframe_count"]:
            changes.append(PropertyChange(
                f"{slot}.keyframe_count",
                curve_a["keyframe_count"],
                curve_b["keyframe_count"],
            ))

        if not _frames_equal(curve_a["frame_start"], curve_b["frame_start"]):
            changes.append(PropertyChange(
                f"{slot}.frame_start",
                curve_a["frame_start"],
                curve_b["frame_start"],
            ))

        if not _frames_equal(curve_a["frame_end"], curve_b["frame_end"]):
            changes.append(PropertyChange(
                f"{slot}.frame_end",
                curve_a["frame_end"],
                curve_b["frame_end"],
            ))

        if curve_a["interpolation"] != curve_b["interpolation"]:
            changes.append(PropertyChange(
                f"{slot}.interpolation",
                curve_a["interpolation"],
                curve_b["interpolation"],
            ))

        if curve_a["extrapolation"] != curve_b["extrapolation"]:
            changes.append(PropertyChange(
                f"{slot}.extrapolation",
                curve_a["extrapolation"],
                curve_b["extrapolation"],
            ))

    return FCurveDiff(object_name=obj_name, changes=changes)


def diff_all_fcurves(
    objs_a: dict[str, dict],
    objs_b: dict[str, dict],
) -> list[FCurveDiff]:

    results: list[FCurveDiff] = []

    for name in sorted(set(objs_a) & set(objs_b)):
        diff = diff_fcurves(
            obj_name=name,
            curves_a=objs_a[name].get("fcurves", []),
            curves_b=objs_b[name].get("fcurves", []),
        )
        if diff.changes:
            results.append(diff)

    return results