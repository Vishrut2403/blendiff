from __future__ import annotations


# Properties to extract per modifier type.
# Each entry is a list of (bpy_attr, output_key) pairs.
_MOD_PROPS: dict[str, list[tuple[str, str]]] = {
	"SUBSURF": [
		("levels",              "levels"),
		("render_levels",       "render_levels"),
		("subdivision_type",    "subdivision_type"),  # CATMULL_CLARK / SIMPLE
		("use_creases",         "use_creases"),
	],
	"MIRROR": [
		("use_axis",            "use_axis"),           # tuple (x, y, z)
		("use_bisect_axis",     "use_bisect_axis"),
		("use_clip",            "use_clip"),
		("merge_threshold",     "merge_threshold"),
	],
	"ARRAY": [
		("fit_type",            "fit_type"),           # FIXED_COUNT / FIT_LENGTH / FIT_CURVE
		("count",               "count"),
		("relative_offset_displace", "relative_offset"),
		("use_relative_offset", "use_relative_offset"),
		("use_constant_offset", "use_constant_offset"),
	],
	"BEVEL": [
		("width",               "width"),
		("segments",            "segments"),
		("limit_method",        "limit_method"),
		("miter_outer",         "miter_outer"),
		("affect",              "affect"),             # VERTICES / EDGES
	],
	"BOOLEAN": [
		("operation",           "operation"),          # INTERSECT / UNION / DIFFERENCE
		("solver",              "solver"),             # FAST / EXACT
		("object",              "object_name"),        # resolved to name below
	],
	"SOLIDIFY": [
		("thickness",           "thickness"),
		("offset",              "offset"),
		("use_even_offset",     "use_even_offset"),
		("solidify_mode",       "solidify_mode"),
	],
	"ARMATURE": [
		("object",              "object_name"),
		("use_deform_preserve_volume", "use_deform_preserve_volume"),
		("use_vertex_groups",   "use_vertex_groups"),
	],
	"DECIMATE": [
		("decimate_type",       "decimate_type"),
		("ratio",               "ratio"),
		("iterations",          "iterations"),
		("angle_limit",         "angle_limit"),
	],
	"DISPLACE": [
		("strength",            "strength"),
		("direction",           "direction"),
		("space",               "space"),
	],
	"SMOOTH": [
		("factor",              "factor"),
		("iterations",          "iterations"),
		("use_x",               "use_x"),
		("use_y",               "use_y"),
		("use_z",               "use_z"),
	],
	"SKIN": [
		("branch_smoothing",    "branch_smoothing"),
		("use_smooth_shade",    "use_smooth_shade"),
	],
	"SCREW": [
		("angle",               "angle"),
		("screw_offset",        "screw_offset"),
		("steps",               "steps"),
		("render_steps",        "render_steps"),
		("axis",                "axis"),
	],
	"REMESH": [
		("mode",                "mode"),
		("octree_depth",        "octree_depth"),
		("voxel_size",          "voxel_size"),
		("adaptivity",          "adaptivity"),
	],
	"WELD": [
		("merge_threshold",     "merge_threshold"),
		("mode",                "mode"),
	],
	"TRIANGULATE": [
		("quad_method",         "quad_method"),
		("ngon_method",         "ngon_method"),
		("min_vertices",        "min_vertices"),
	],
	"WEIGHTED_NORMAL": [
		("mode",                "mode"),
		("weight",              "weight"),
		("thresh",              "thresh"),
	],
}

# Attributes that hold object references — resolve to name string
_OBJ_REF_ATTRS = {"object_name"}


def _resolve(mod, bpy_attr: str, output_key: str):
	"""Get a modifier attribute and resolve object refs to names."""
	val = getattr(mod, bpy_attr, None)
	if output_key == "object_name":
		# val is a bpy Object or None
		return val.name if val is not None else None
	# Convert iterables (e.g. use_axis tuple) to plain lists
	if hasattr(val, "__iter__") and not isinstance(val, str):
		try:
			return list(val)
		except Exception:
			pass
	return val


def extract_modifier_stack(obj) -> list[dict]:
	"""
	Parameters
	----------
	obj : bpy.types.Object
		Any Blender object.

	Returns
	-------
	list[dict]
		Ordered list of modifier dicts, one per modifier in stack order.
		Each dict has at minimum: index, name, type, show_viewport,
		show_render, is_active. Type-specific params are added when known.
	"""
	result = []
	for i, mod in enumerate(obj.modifiers):
		entry: dict = {
			"index":        i,
			"name":         mod.name,
			"type":         mod.type,
			"show_viewport": mod.show_viewport,
			"show_render":  mod.show_render,
			"is_active":    getattr(mod, "is_active", True),
		}

		# Extract type-specific key properties
		props = _MOD_PROPS.get(mod.type, [])
		params: dict = {}
		for bpy_attr, output_key in props:
			params[output_key] = _resolve(mod, bpy_attr, output_key)

		if params:
			entry["params"] = params

		result.append(entry)

	return result