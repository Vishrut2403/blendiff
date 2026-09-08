from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.scene_custom_prop_diff import SceneCustomPropDiff
from .custom_prop_diff import _values_equal


def diff_scene_custom_props(
	props_a: dict | None,
	props_b: dict | None,
	prefix: str = "scene.custom_props",
) -> SceneCustomPropDiff:

	a = props_a or {}
	b = props_b or {}

	changes: list[PropertyChange] = []
	all_keys = sorted(set(a) | set(b))

	for key in all_keys:
		in_a = key in a
		in_b = key in b
		path = f"{prefix}.{key}"

		if in_a and not in_b:
			changes.append(PropertyChange(path, a[key], None))
		elif in_b and not in_a:
			changes.append(PropertyChange(path, None, b[key]))
		elif not _values_equal(a[key], b[key]):
			changes.append(PropertyChange(path, a[key], b[key]))

	return SceneCustomPropDiff(changes=changes)