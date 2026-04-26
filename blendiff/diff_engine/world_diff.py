from __future__ import annotations
from typing import Any

from blendiff.data_model.diff import PropertyChange, WorldDiff

_EPSILON = 1e-6

_FLOAT_PROPS = {
	"ao_factor", "ao_distance",
	"background_strength", "hdri_strength",
}

_FLOAT_VEC_PROPS = {
	"color",
	"background_color",
}


def _floats_equal(a: float, b: float) -> bool:
	return abs(a - b) < _EPSILON


def _vecs_equal(a: list, b: list) -> bool:
	if len(a) != len(b):
		return False
	return all(_floats_equal(x, y) for x, y in zip(a, b))


def _values_equal(key: str, a: Any, b: Any) -> bool:
	if key in _FLOAT_PROPS:
		if isinstance(a, float) and isinstance(b, float):
			return _floats_equal(a, b)
	if key in _FLOAT_VEC_PROPS:
		if isinstance(a, list) and isinstance(b, list):
			return _vecs_equal(a, b)
	return a == b


def diff_world_data(
	world_a: dict | None,
	world_b: dict | None,
) -> "WorldDiff":
	"""
	Compare two world data dicts.

	Parameters
	----------
	world_a, world_b : dict | None
		Plain dicts as produced by extract_world_data().
		None means no world was assigned in that snapshot.

	Returns
	-------
	WorldDiff
	"""
	changes: list[PropertyChange] = []

	if world_a is None and world_b is None:
		return WorldDiff(changes=changes)

	if world_a is None:
		changes.append(PropertyChange(
			property_path="world",
			old_value=None,
			new_value=world_b.get("name"),
		))
		return WorldDiff(changes=changes)

	if world_b is None:
		changes.append(PropertyChange(
			property_path="world",
			old_value=world_a.get("name"),
			new_value=None,
		))
		return WorldDiff(changes=changes)

	all_keys = set(world_a) | set(world_b)
	for key in sorted(all_keys):
		val_a = world_a.get(key)
		val_b = world_b.get(key)
		if not _values_equal(key, val_a, val_b):
			changes.append(PropertyChange(
				property_path=f"world.{key}",
				old_value=val_a,
				new_value=val_b,
			))

	return WorldDiff(changes=changes)