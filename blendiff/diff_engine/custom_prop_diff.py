from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.custom_prop_diff import CustomPropDiff

_FLOAT_EPSILON = 1e-5


def _values_equal(a: object, b: object) -> bool:

	if type(a) is not type(b):
		# Allow int/float comparison
		if isinstance(a, (int, float)) and isinstance(b, (int, float)):
			return abs(float(a) - float(b)) < _FLOAT_EPSILON
		return False
	if isinstance(a, float):
		return abs(a - b) < _FLOAT_EPSILON
	if isinstance(a, (list, tuple)):
		if len(a) != len(b):
			return False
		return all(_values_equal(x, y) for x, y in zip(a, b))
	if isinstance(a, dict):
		if set(a.keys()) != set(b.keys()):
			return False
		return all(_values_equal(a[k], b[k]) for k in a)
	return a == b


def diff_custom_props(
	obj_name: str,
	props_a: dict | None,
	props_b: dict | None,
	prefix: str = "custom_props",
) -> CustomPropDiff:

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

	return CustomPropDiff(object_name=obj_name, changes=changes)


def diff_all_custom_props(
	objs_a: dict[str, dict],
	objs_b: dict[str, dict],
) -> list[CustomPropDiff]:

	results: list[CustomPropDiff] = []

	for name in sorted(set(objs_a) & set(objs_b)):
		diff = diff_custom_props(
			obj_name=name,
			props_a=objs_a[name].get("custom_props"),
			props_b=objs_b[name].get("custom_props"),
		)
		if diff.changes:
			results.append(diff)

	return results