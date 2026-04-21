"""
Pure-Python comparison of two render-settings dicts.
No bpy dependency — fully unit-testable without Blender.
"""

from __future__ import annotations
from typing import Any

from blendiff.data_model.diff import PropertyChange, RenderDiff

_FLOAT_PROPS = {"fps_base", "exposure", "gamma"}
_EPSILON = 1e-6

_SUB_DICTS = {
    "cycles": "cycles",
    "eevee": "eevee",
}


def _floats_equal(a: float, b: float) -> bool:
    return abs(a - b) < _EPSILON


def _values_equal(key: str, a: Any, b: Any) -> bool:
    if key in _FLOAT_PROPS and isinstance(a, float) and isinstance(b, float):
        return _floats_equal(a, b)
    return a == b


def diff_render_settings(snapshot_a: dict, snapshot_b: dict) -> RenderDiff:
    """
    Compare two render-settings dicts (as produced by render_extractor).

    Parameters
    ----------
    snapshot_a, snapshot_b : dict
        Plain dicts — the ``render`` sub-dict stored in each SerializedScene.

    Returns
    -------
    RenderDiff
        Contains a PropertyChange for every property that differs.
    """
    changes: list[PropertyChange] = []

    def _compare(dict_a: dict, dict_b: dict, prefix: str) -> None:
        all_keys = set(dict_a) | set(dict_b)
        for key in sorted(all_keys):
            path = f"{prefix}.{key}" if prefix else key

            val_a = dict_a.get(key)
            val_b = dict_b.get(key)

            # Both are sub-dicts → recurse
            if isinstance(val_a, dict) and isinstance(val_b, dict):
                _compare(val_a, val_b, path)
                continue

            # One side missing
            if val_a is None and val_b is not None:
                changes.append(PropertyChange(
                    property_path=path,
                    old_value=None,
                    new_value=val_b,
                ))
                continue
            if val_a is not None and val_b is None:
                changes.append(PropertyChange(
                    property_path=path,
                    old_value=val_a,
                    new_value=None,
                ))
                continue

            # Regular comparison
            if not _values_equal(key, val_a, val_b):
                changes.append(PropertyChange(
                    property_path=path,
                    old_value=val_a,
                    new_value=val_b,
                ))

    _compare(snapshot_a, snapshot_b, "render")
    return RenderDiff(changes=changes)