from __future__ import annotations
from typing import Any

from ..data_model.diff import PropertyChange

_EPSILON = 1e-5

_FLOAT_PARAMS = {
	"merge_threshold", "width", "ratio", "angle_limit", "thickness",
	"offset", "strength", "factor", "voxel_size", "adaptivity",
	"branch_smoothing", "angle", "screw_offset", "weight", "thresh",
}


def _feq(a: float, b: float) -> bool:
	return abs(a - b) < _EPSILON


def _params_equal(key: str, a: Any, b: Any) -> bool:
	if a is None and b is None:
		return True
	if a is None or b is None:
		return False
	if key in _FLOAT_PARAMS and isinstance(a, float) and isinstance(b, float):
		return _feq(a, b)
	if isinstance(a, list) and isinstance(b, list):
		if len(a) != len(b):
			return False
		return all(
			_feq(x, y) if isinstance(x, float) and isinstance(y, float) else x == y
			for x, y in zip(a, b)
		)
	return a == b


def diff_modifier_stack(
	stack_a: list[dict],
	stack_b: list[dict],
	prefix: str = "modifiers",
) -> list[PropertyChange]:
	"""
	Compare two modifier stacks.

	Parameters
	----------
	stack_a, stack_b : list[dict]
		Ordered lists as produced by extract_modifier_stack().
	prefix : str
		Property path prefix.

	Returns
	-------
	list[PropertyChange]
	"""
	changes: list[PropertyChange] = []

	names_a = [m["name"] for m in stack_a or []]
	names_b = [m["name"] for m in stack_b or []]

	# A reorder has to be recognised before anything else, because pairing by
	# slot turns it into nonsense: swapping a Bevel and a Subsurf reads as
	# "slot 0 changed type, slot 1 changed type", which is both wrong and
	# unapplicable. Blender keeps modifier names unique per object, so when
	# both sides hold the same names in a different order, pairing by name is
	# the honest reading.
	reordered = (
		len(set(names_a)) == len(names_a)
		and set(names_a) == set(names_b)
		and names_a != names_b
	)

	if reordered:
		changes.append(PropertyChange(
			property_path=f"{prefix}.order",
			old_value=names_a,
			new_value=names_b,
		))
		by_name = {m["name"]: m for m in stack_a}
		pairs = [
			(index, by_name[mod["name"]], mod)
			for index, mod in enumerate(stack_b)
		]
	else:
		map_a = {m["index"]: m for m in stack_a or []}
		map_b = {m["index"]: m for m in stack_b or []}
		pairs = [
			(idx, map_a.get(idx), map_b.get(idx))
			for idx in sorted(set(map_a) | set(map_b))
		]

	for idx, mod_a, mod_b in pairs:
		path_base = f"{prefix}[{idx}]"

		# Added
		if mod_a is None:
			changes.append(PropertyChange(
				property_path=f"{path_base}",
				old_value=None,
				new_value=f"{mod_b['type']}({mod_b['name']})",
			))
			continue

		# Removed
		if mod_b is None:
			changes.append(PropertyChange(
				property_path=f"{path_base}",
				old_value=f"{mod_a['type']}({mod_a['name']})",
				new_value=None,
			))
			continue

		# Type changed — report as a single slot replacement
		if mod_a.get("type") != mod_b.get("type"):
			changes.append(PropertyChange(
				property_path=f"{path_base}.type",
				old_value=mod_a.get("type"),
				new_value=mod_b.get("type"),
			))
			continue  # skip param diff when type changed — it's noise

		# Name changed
		if mod_a.get("name") != mod_b.get("name"):
			changes.append(PropertyChange(
				property_path=f"{path_base}.name",
				old_value=mod_a.get("name"),
				new_value=mod_b.get("name"),
			))

		# Visibility
		for vis_key in ("show_viewport", "show_render"):
			if mod_a.get(vis_key) != mod_b.get(vis_key):
				changes.append(PropertyChange(
					property_path=f"{path_base}.{vis_key}",
					old_value=mod_a.get(vis_key),
					new_value=mod_b.get(vis_key),
				))

		# Params
		#
		# Only keys both sides actually recorded. A key present on one side and
		# absent on the other means one snapshot predates BlenDiff capturing
		# it, not that the value changed. Geometry Nodes made this visible:
		# before 0.9.0 a node group's inputs were not captured at all, so
		# comparing an older snapshot against a newer one reported every input
		# as newly set. An unset value is recorded as null rather than left
		# out, so absence is unambiguous.
		params_a = mod_a.get("params", {})
		params_b = mod_b.get("params", {})
		for key in sorted(set(params_a) & set(params_b)):
			val_a = params_a.get(key)
			val_b = params_b.get(key)
			if not _params_equal(key, val_a, val_b):
				changes.append(PropertyChange(
					property_path=f"{path_base}.{key}",
					old_value=val_a,
					new_value=val_b,
				))

	return changes
