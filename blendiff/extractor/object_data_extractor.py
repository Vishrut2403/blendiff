"""
blendiff.extractor.object_data_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Type-specific data for the object types that had none.

Four of Blender's thirteen object types had their data captured: meshes,
armatures, cameras and lights. The other nine had their transform, modifiers
and constraints recorded and nothing else, so changing a text object's
contents, a curve's bevel depth or a lattice's resolution produced no diff at
all. BlenDiff reported a clean scene for an edit that visibly changed the
render.

Attribute maps rather than nine hand-written functions. Each type is a list of
(bpy attribute, snapshot key) pairs read off the object's data, which is the
same shape the camera and light extractors use, and it keeps adding a property
to a one-line change.

Object references, such as a curve's taper or bevel object, are recorded by
name. Storing anything else would mean a snapshot holding a pointer that means
nothing once the file is reopened.
"""

from __future__ import annotations

import logging

from .coerce import to_jsonable

log = logging.getLogger(__name__)

#: Attributes read from obj.data, per object type.
_DATA_PROPS: dict[str, list[tuple[str, str]]] = {
	"CURVE": [
		("dimensions",           "dimensions"),       # 2D or 3D
		("resolution_u",         "resolution_u"),
		("render_resolution_u",  "render_resolution_u"),
		("bevel_depth",          "bevel_depth"),
		("bevel_resolution",     "bevel_resolution"),
		("extrude",              "extrude"),
		("offset",               "offset"),
		("fill_mode",            "fill_mode"),
		("use_fill_caps",        "use_fill_caps"),
		("twist_mode",           "twist_mode"),
		("taper_object",         "taper_object"),     # resolved to a name
		("bevel_object",         "bevel_object"),     # resolved to a name
	],
	"SURFACE": [
		("resolution_u",         "resolution_u"),
		("resolution_v",         "resolution_v"),
		("render_resolution_u",  "render_resolution_u"),
		("render_resolution_v",  "render_resolution_v"),
	],
	"FONT": [
		("body",                 "body"),             # the text itself
		("size",                 "size"),
		("shear",                "shear"),
		("space_character",      "space_character"),
		("space_word",           "space_word"),
		("space_line",           "space_line"),
		("align_x",              "align_x"),
		("align_y",              "align_y"),
		("offset_x",             "offset_x"),
		("offset_y",             "offset_y"),
		("extrude",              "extrude"),
		("bevel_depth",          "bevel_depth"),
		("font",                 "font"),             # resolved to a name
	],
	"META": [
		("resolution",           "resolution"),
		("render_resolution",    "render_resolution"),
		("threshold",            "threshold"),
	],
	"LATTICE": [
		("points_u",             "points_u"),
		("points_v",             "points_v"),
		("points_w",             "points_w"),
		("interpolation_type_u", "interpolation_type_u"),
		("use_outside",          "use_outside"),
	],
	"VOLUME": [
		("filepath",             "filepath"),
		("frame_start",          "frame_start"),
		("frame_duration",       "frame_duration"),
		("sequence_mode",        "sequence_mode"),
	],
	"SPEAKER": [
		("volume",               "volume"),
		("pitch",                "pitch"),
		("muted",                "muted"),
		("distance_max",         "distance_max"),
		("distance_reference",   "distance_reference"),
		("sound",                "sound"),            # resolved to a name
	],
	"GREASEPENCIL": [
		("stroke_depth_order",   "stroke_depth_order"),
	],
}

#: Empties carry no data block at all; their settings live on the object.
_EMPTY_PROPS: list[tuple[str, str]] = [
	("empty_display_type",  "display_type"),
	("empty_display_size",  "display_size"),
	("empty_image_depth",   "image_depth"),
]

#: Types this module knows how to read, for the schema's benefit.
SUPPORTED_TYPES = frozenset(_DATA_PROPS) | {"EMPTY"}


def _value(source, attr: str):
	"""One attribute, with datablock references reduced to their name."""
	value = getattr(source, attr, None)
	# Curve taper objects, text fonts and speaker sounds are all datablocks.
	# A name is the only part of one that still means something in a snapshot.
	if value is not None and not isinstance(value, (str, bool, int, float)):
		name = getattr(value, "name", None)
		if name is not None:
			return name
	return to_jsonable(value)


def extract_object_data(obj) -> dict | None:
	"""
	Type-specific data for one object, or None when there is nothing to record.

	Returns None rather than an empty dict for a type this does not cover, so
	"no data for this type" stays distinguishable from "this type has data and
	all of it happens to be empty".
	"""
	obj_type = getattr(obj, "type", None)

	if obj_type == "EMPTY":
		return {key: _value(obj, attr) for attr, key in _EMPTY_PROPS}

	props = _DATA_PROPS.get(obj_type)
	if props is None:
		return None

	data = getattr(obj, "data", None)
	if data is None:
		return None

	result = {}
	for attr, key in props:
		try:
			result[key] = _value(data, attr)
		except Exception as exc:
			# One unreadable property must not cost the whole object its data.
			log.warning("Could not read %s.%s: %s", obj_type, attr, exc)
	return result
