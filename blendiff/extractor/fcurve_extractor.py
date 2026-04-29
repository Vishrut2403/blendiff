from __future__ import annotations

import logging
from typing import Any
from collections import Counter

log = logging.getLogger(__name__)


def _dominant_interpolation(keyframes: Any) -> str:
	if not keyframes:
		return "CONSTANT"
	counts = Counter(kp.interpolation for kp in keyframes)
	return counts.most_common(1)[0][0]


def _extract_fcurve(fc: Any) -> dict:
	keyframes = fc.keyframe_points
	count = len(keyframes)
	if count == 0:
		frame_start = frame_end = 0.0
	elif count == 1:
		frame_start = frame_end = round(keyframes[0].co[0], 4)
	else:
		frame_start = round(keyframes[0].co[0], 4)
		frame_end   = round(keyframes[-1].co[0], 4)
	return {
		"data_path":      fc.data_path,
		"array_index":    fc.array_index,
		"keyframe_count": count,
		"frame_start":    frame_start,
		"frame_end":      frame_end,
		"interpolation":  _dominant_interpolation(keyframes),
		"extrapolation":  fc.extrapolation,
	}


def _iter_fcurves(action: Any):
	"""
	Yield all FCurve objects from an action.

	Handles both the legacy API (action.fcurves, Blender <= 4.x)
	and the new layered action API (Blender 5.x).
	"""
	# Legacy API
	if hasattr(action, "fcurves"):
		yield from action.fcurves
		return

	# Blender 5.x layered action API
	try:
		for layer in action.layers:
			for strip in layer.strips:
				# strip.channelbag() requires a binding — iterate all bindings
				for channelbag in strip.channelbags:
					yield from channelbag.fcurves
	except Exception as exc:
		log.debug("Could not iterate layered action fcurves: %s", exc)


def extract_fcurves(obj: Any) -> list[dict]:
	"""
	Extract F-curve summaries from a bpy.types.Object.

	Compatible with both Blender 4.x (action.fcurves) and
	Blender 5.x (layered action API).

	Returns plain dicts — no bpy types leak downstream.
	"""
	try:
		anim = obj.animation_data
		if anim is None or anim.action is None:
			return []
	except Exception as exc:
		log.warning("Could not access animation data for %r: %s", obj.name, exc)
		return []

	result = []
	for fc in _iter_fcurves(anim.action):
		try:
			result.append(_extract_fcurve(fc))
		except Exception as exc:
			log.warning(
				"Failed to extract F-curve %r[%d] on %r: %s",
				fc.data_path, fc.array_index, obj.name, exc,
			)

	result.sort(key=lambda x: (x["data_path"], x["array_index"]))
	return result