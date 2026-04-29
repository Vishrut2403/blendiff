from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Per-constraint-type properties to extract.
# (bpy_attr, output_key) — object refs are resolved to names.
_CONSTRAINT_PROPS: dict[str, list[tuple[str, str]]] = {
	"COPY_LOCATION": [
		("target",      "target"),
		("subtarget",   "subtarget"),   # bone name
		("use_x",       "use_x"),
		("use_y",       "use_y"),
		("use_z",       "use_z"),
		("use_offset",  "use_offset"),
	],
	"COPY_ROTATION": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("use_x",       "use_x"),
		("use_y",       "use_y"),
		("use_z",       "use_z"),
		("mix_mode",    "mix_mode"),
	],
	"COPY_SCALE": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("use_x",       "use_x"),
		("use_y",       "use_y"),
		("use_z",       "use_z"),
		("use_offset",  "use_offset"),
	],
	"COPY_TRANSFORMS": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("mix_mode",    "mix_mode"),
	],
	"LIMIT_LOCATION": [
		("use_min_x",   "use_min_x"),
		("use_max_x",   "use_max_x"),
		("use_min_y",   "use_min_y"),
		("use_max_y",   "use_max_y"),
		("use_min_z",   "use_min_z"),
		("use_max_z",   "use_max_z"),
		("min_x",       "min_x"),
		("max_x",       "max_x"),
		("min_y",       "min_y"),
		("max_y",       "max_y"),
		("min_z",       "min_z"),
		("max_z",       "max_z"),
	],
	"LIMIT_ROTATION": [
		("use_limit_x", "use_limit_x"),
		("use_limit_y", "use_limit_y"),
		("use_limit_z", "use_limit_z"),
		("min_x",       "min_x"),
		("max_x",       "max_x"),
		("min_y",       "min_y"),
		("max_y",       "max_y"),
		("min_z",       "min_z"),
		("max_z",       "max_z"),
	],
	"LIMIT_SCALE": [
		("use_min_x",   "use_min_x"),
		("use_max_x",   "use_max_x"),
		("use_min_y",   "use_min_y"),
		("use_max_y",   "use_max_y"),
		("use_min_z",   "use_min_z"),
		("use_max_z",   "use_max_z"),
		("min_x",       "min_x"),
		("max_x",       "max_x"),
		("min_y",       "min_y"),
		("max_y",       "max_y"),
		("min_z",       "min_z"),
		("max_z",       "max_z"),
	],
	"TRACK_TO": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("track_axis",  "track_axis"),
		("up_axis",     "up_axis"),
	],
	"DAMPED_TRACK": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("track_axis",  "track_axis"),
	],
	"LOCKED_TRACK": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("track_axis",  "track_axis"),
		("lock_axis",   "lock_axis"),
	],
	"STRETCH_TO": [
		("target",      "target"),
		("subtarget",   "subtarget"),
		("rest_length", "rest_length"),
		("bulge",       "bulge"),
		("keep_axis",   "keep_axis"),
	],
	"IK": [
		("target",          "target"),
		("subtarget",       "subtarget"),
		("pole_target",     "pole_target"),
		("pole_subtarget",  "pole_subtarget"),
		("pole_angle",      "pole_angle"),
		("chain_count",     "chain_count"),
		("iterations",      "iterations"),
		("use_tail",        "use_tail"),
		("use_stretch",     "use_stretch"),
	],
	"FLOOR": [
		("target",          "target"),
		("subtarget",       "subtarget"),
		("floor_location",  "floor_location"),
		("offset",          "offset"),
		("use_rotation",    "use_rotation"),
	],
	"FOLLOW_PATH": [
		("target",          "target"),
		("use_fixed_location", "use_fixed_location"),
		("offset_factor",   "offset_factor"),
		("forward_axis",    "forward_axis"),
		("up_axis",         "up_axis"),
	],
	"CHILD_OF": [
		("target",          "target"),
		("subtarget",       "subtarget"),
		("use_location_x",  "use_location_x"),
		("use_location_y",  "use_location_y"),
		("use_location_z",  "use_location_z"),
		("use_rotation_x",  "use_rotation_x"),
		("use_rotation_y",  "use_rotation_y"),
		("use_rotation_z",  "use_rotation_z"),
		("use_scale_x",     "use_scale_x"),
		("use_scale_y",     "use_scale_y"),
		("use_scale_z",     "use_scale_z"),
	],
	"PIVOT": [
		("target",          "target"),
		("subtarget",       "subtarget"),
		("rotation_range",  "rotation_range"),
	],
	"SHRINKWRAP": [
		("target",          "target"),
		("shrinkwrap_type", "shrinkwrap_type"),
		("distance",        "distance"),
		("project_axis",    "project_axis"),
	],
	"ACTION": [
		("action",          "action"),      # resolved to name
		("use_bone_object_action", "use_bone_object_action"),
		("frame_start",     "frame_start"),
		("frame_end",       "frame_end"),
		("min",             "min"),
		("max",             "max"),
	],
	"TRANSFORM": [
		("target",          "target"),
		("subtarget",       "subtarget"),
		("map_from",        "map_from"),
		("map_to",          "map_to"),
	],
	"CLAMP_TO": [
		("target",          "target"),
		("main_axis",       "main_axis"),
		("use_cyclic",      "use_cyclic"),
	],
	"SPLINE_IK": [
		("target",          "target"),
		("chain_count",     "chain_count"),
		("use_even_divisions", "use_even_divisions"),
	],
}

# Output keys that hold object or action references — resolve to .name
_REF_KEYS = {"target", "pole_target", "action"}


def _resolve(con: Any, bpy_attr: str, output_key: str) -> Any:
	"""Get a constraint attribute, resolving object/action refs to names."""
	val = getattr(con, bpy_attr, None)
	if output_key in _REF_KEYS:
		return val.name if val is not None else None
	if hasattr(val, "__iter__") and not isinstance(val, str):
		try:
			return list(val)
		except Exception:
			pass
	return val


def extract_constraint_stack(obj: Any) -> list[dict]:
	
	result = []
	for i, con in enumerate(obj.constraints):
		entry: dict = {
			"index":     i,
			"name":      con.name,
			"type":      con.type,
			"enabled":   not con.mute,
			"influence": round(con.influence, 6),
		}

		props = _CONSTRAINT_PROPS.get(con.type, [])
		params: dict = {}
		for bpy_attr, output_key in props:
			try:
				params[output_key] = _resolve(con, bpy_attr, output_key)
			except Exception as exc:
				log.debug("Could not read %r.%s: %s", con.name, bpy_attr, exc)

		if params:
			entry["params"] = params

		result.append(entry)

	return result