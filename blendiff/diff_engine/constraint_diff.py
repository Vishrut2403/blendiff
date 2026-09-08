from __future__ import annotations

from .identity_match import resolve_pairs
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


def _floats_equal_or_none(a, b) -> bool:
	"""Compare two possibly-absent floats without assuming either exists."""
	if a is None or b is None:
		return a is b or a == b
	return _floats_equal(a, b)


def diff_constraint_stack(
	stack_a: list[dict],
	stack_b: list[dict],
	obj_name: str,
	prefix: str = "constraints",
) -> ConstraintDiff:

	changes: list[PropertyChange] = []

	map_a = {c["index"]: c for c in stack_a or []}
	map_b = {c["index"]: c for c in stack_b or []}
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

		# Fields are read with .get so that a constraint entry missing a key —
		# an older snapshot, or an extraction that partially failed — degrades
		# to "no change detected" instead of raising KeyError and taking the
		# entire scene diff down with it.

		# Type changed — treat as a full replacement, no deep dive
		if con_a.get("type") != con_b.get("type"):
			changes.append(PropertyChange(
				f"{slot}.type", con_a.get("type"), con_b.get("type"),
			))
			continue

		# Name changed
		if con_a.get("name") != con_b.get("name"):
			changes.append(PropertyChange(
				f"{slot}.name", con_a.get("name"), con_b.get("name"),
			))

		# Enabled
		if con_a.get("enabled") != con_b.get("enabled"):
			changes.append(PropertyChange(
				f"{slot}.enabled", con_a.get("enabled"), con_b.get("enabled"),
			))

		# Influence
		influence_a = con_a.get("influence")
		influence_b = con_b.get("influence")
		if not _floats_equal_or_none(influence_a, influence_b):
			changes.append(PropertyChange(
				f"{slot}.influence", influence_a, influence_b,
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
	pairs: list[tuple[str, str]] | None = None,
) -> list[ConstraintDiff]:
	
	results: list[ConstraintDiff] = []

	for name_a, name_b in resolve_pairs(objs_a, objs_b, pairs):
		diff = diff_constraint_stack(
			stack_a=objs_a[name_a].get("constraint_stack", []),
			stack_b=objs_b[name_b].get("constraint_stack", []),
			obj_name=name_b,
		)
		if diff.changes:
			results.append(diff)

	return results