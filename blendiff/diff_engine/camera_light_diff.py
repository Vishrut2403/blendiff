from __future__ import annotations
from typing import Any

from blendiff.data_model.diff import PropertyChange

_EPSILON = 1e-6

# Float properties that need epsilon comparison
_FLOAT_PROPS = {
	# camera
	"focal_length", "sensor_width", "clip_start", "clip_end",
	"ortho_scale", "shift_x", "shift_y", "dof_distance", "dof_fstop",
	# light
	"energy", "shadow_soft_size", "spot_size", "spot_blend",
	"size", "size_y", "angle",
}


def _floats_equal(a: float, b: float) -> bool:
	return abs(a - b) < _EPSILON


def _values_equal(key: str, a: Any, b: Any) -> bool:
	if key in _FLOAT_PROPS and isinstance(a, float) and isinstance(b, float):
		return _floats_equal(a, b)
	# color is a list of floats
	if key == "color" and isinstance(a, list) and isinstance(b, list):
		if len(a) != len(b):
			return False
		return all(_floats_equal(x, y) for x, y in zip(a, b))
	return a == b


def diff_camera_data(
	cam_a: dict | None,
	cam_b: dict | None,
	prefix: str = "camera",
) -> list[PropertyChange]:
	"""
	Compare two camera data dicts.

	Parameters
	----------
	cam_a, cam_b : dict | None
		Plain dicts as produced by extract_camera_data().
		None means the camera data was not present in that snapshot.
	prefix : str
		Property path prefix, e.g. "camera".

	Returns
	-------
	list[PropertyChange]
	"""
	if cam_a is None and cam_b is None:
		return []
	if cam_a is None:
		return [PropertyChange(property_path=prefix, old_value=None, new_value=cam_b)]
	if cam_b is None:
		return [PropertyChange(property_path=prefix, old_value=cam_a, new_value=None)]

	changes: list[PropertyChange] = []
	all_keys = set(cam_a) | set(cam_b)

	for key in sorted(all_keys):
		val_a = cam_a.get(key)
		val_b = cam_b.get(key)
		if not _values_equal(key, val_a, val_b):
			changes.append(PropertyChange(
				property_path=f"{prefix}.{key}",
				old_value=val_a,
				new_value=val_b,
			))

	return changes


def diff_light_data(
	light_a: dict | None,
	light_b: dict | None,
	prefix: str = "light",
) -> list[PropertyChange]:
	"""
	Compare two light data dicts.

	Parameters
	----------
	light_a, light_b : dict | None
		Plain dicts as produced by extract_light_data().
		None means the light data was not present in that snapshot.
	prefix : str
		Property path prefix, e.g. "light".

	Returns
	-------
	list[PropertyChange]
	"""
	if light_a is None and light_b is None:
		return []
	if light_a is None:
		return [PropertyChange(property_path=prefix, old_value=None, new_value=light_b)]
	if light_b is None:
		return [PropertyChange(property_path=prefix, old_value=light_a, new_value=None)]

	changes: list[PropertyChange] = []
	all_keys = set(light_a) | set(light_b)

	for key in sorted(all_keys):
		val_a = light_a.get(key)
		val_b = light_b.get(key)
		if not _values_equal(key, val_a, val_b):
			changes.append(PropertyChange(
				property_path=f"{prefix}.{key}",
				old_value=val_a,
				new_value=val_b,
			))

	return changes
