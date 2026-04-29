from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.constraint_diff import ConstraintDiff

_FLOAT_KEYS = {
	"influence", "pole_angle", "rest_length", "bulge", "offset",
	"offset_factor", "distance", "min_x", "max_x", "min_y", "max_y",
	"min_z", "max_z", "min", "max",
}
_EPSILON = 1e-5


def _floats_equal(a: float, b: float) -> bool:
	return abs(a - b) < _EPSILON


def _params_changes(
	params_a: dict,
	params_b: dict,
	prefix: str,
) -> list[PropertyChange]:
	changes: list[PropertyChange] = []
	all_keys = sorted(set(params_a) | set(params_b))
	for key in all_keys:
		val_a = params_a.get(key)
		val_b = params_b.get(key)
		if key in _FLOAT_KEYS:
			if val_a is None or val_b is None:
				if val_a != val_b:
					changes.append(PropertyChange(f"{prefix}.{key}", val_a, val_b))
			elif not _floats_equal(float(val_a), float(val_b)):
				changes.append(PropertyChange(f"{prefix}.{key}", val_a, val_b))
		else:
			if val_a != val_b:
				changes.append(PropertyChange(f"{prefix}.{key}", val_a, val_b))
	return changes


def diff_constraint_stack(
	stack_a: list[dict],
	stack_b: list[dict],
	obj_name: str,
	prefix: str = "constraints",
) -> ConstraintDiff:

	changes: list[PropertyChange] = []

	map_a = {c["index"]: c for c in stack_a}
	map_b = {c["index"]: c for c in stack_b}
	all_indices = sorted(set(map_a) | set(map_b))

	for idx in all_indices:
		con_a = map_a.get(idx)
		con_b = map_b.get(idx)
		slot = f"{prefix}[{idx}]"

		if con_a is None:
			changes.append(PropertyChange(slot, None, con_b.get("name")))
			continue

		if con_b is None:
			changes.append(PropertyChange(slot, con_a.get("name"), None))
			continue

		# Type changed — treat as a full replacement, no deep dive
		if con_a["type"] != con_b["type"]:
			changes.append(PropertyChange(f"{slot}.type", con_a["type"], con_b["type"]))
			continue

		# Name changed
		if con_a["name"] != con_b["name"]:
			changes.append(PropertyChange(f"{slot}.name", con_a["name"], con_b["name"]))

		# Enabled
		if con_a["enabled"] != con_b["enabled"]:
			changes.append(PropertyChange(f"{slot}.enabled", con_a["enabled"], con_b["enabled"]))

		# Influence
		if not _floats_equal(con_a["influence"], con_b["influence"]):
			changes.append(PropertyChange(
				f"{slot}.influence", con_a["influence"], con_b["influence"]
			))

		# Type-specific params
		params_a = con_a.get("params", {})
		params_b = con_b.get("params", {})
		if params_a or params_b:
			changes.extend(_params_changes(params_a, params_b, slot))

	return ConstraintDiff(object_name=obj_name, changes=changes)


def diff_all_constraints(
	objs_a: dict[str, dict],
	objs_b: dict[str, dict],
) -> list[ConstraintDiff]:
	
	results: list[ConstraintDiff] = []

	for name in sorted(set(objs_a) & set(objs_b)):
		diff = diff_constraint_stack(
			stack_a=objs_a[name].get("constraint_stack", []),
			stack_b=objs_b[name].get("constraint_stack", []),
			obj_name=name,
		)
		if diff.changes:
			results.append(diff)

	return results