from __future__ import annotations
from typing import Any

from blendiff.data_model.diff import PropertyChange

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

	max_len = max(len(stack_a), len(stack_b), 1)
	map_a = {m["index"]: m for m in stack_a}
	map_b = {m["index"]: m for m in stack_b}
	all_indices = sorted(set(map_a) | set(map_b))

	for idx in all_indices:
		mod_a = map_a.get(idx)
		mod_b = map_b.get(idx)
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
		if mod_a["type"] != mod_b["type"]:
			changes.append(PropertyChange(
				property_path=f"{path_base}.type",
				old_value=mod_a["type"],
				new_value=mod_b["type"],
			))
			continue  # skip param diff when type changed — it's noise

		# Name changed
		if mod_a["name"] != mod_b["name"]:
			changes.append(PropertyChange(
				property_path=f"{path_base}.name",
				old_value=mod_a["name"],
				new_value=mod_b["name"],
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
		params_a = mod_a.get("params", {})
		params_b = mod_b.get("params", {})
		all_param_keys = sorted(set(params_a) | set(params_b))
		for key in all_param_keys:
			val_a = params_a.get(key)
			val_b = params_b.get(key)
			if not _params_equal(key, val_a, val_b):
				changes.append(PropertyChange(
					property_path=f"{path_base}.{key}",
					old_value=val_a,
					new_value=val_b,
				))

	# Detect full stack reorder — same modifiers, different order
	names_a = [m["name"] for m in stack_a]
	names_b = [m["name"] for m in stack_b]
	if set(names_a) == set(names_b) and names_a != names_b and not changes:
		changes.append(PropertyChange(
			property_path=f"{prefix}.order",
			old_value=names_a,
			new_value=names_b,
		))

	return changes
