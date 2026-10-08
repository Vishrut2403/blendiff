from __future__ import annotations

from .coerce import to_jsonable


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
	# Vectors, colours and the rest of mathutils do not expose __iter__, so a
	# hasattr check let them through unconverted and json.dumps then refused
	# the whole snapshot. Attempt the conversion instead of asking.
	return to_jsonable(val)


# Geometry Nodes
#
# A Geometry Nodes modifier has no fixed set of properties: its inputs are
# whatever the node group exposes. They are stored on the modifier as
# IDProperties keyed by an opaque identifier ("Socket_3"), while the name the
# artist sees ("Density") lives on the node group's interface. Reporting the
# identifier would be useless, so the interface is walked to recover names.
#
# Without this a Geometry Nodes modifier was captured as name, type and
# visibility only, so changing any input, which is the entire point of a node
# group, produced no diff at all.

def _socket_value(value):
	"""One input value, as something JSON can hold."""
	# Object, Collection, Material and Image sockets hold a datablock. Every
	# one of those is recorded by name, as object references are elsewhere.
	if value is not None and not isinstance(value, str) and hasattr(value, "name"):
		return value.name
	return to_jsonable(value)


def extract_node_group_inputs(mod) -> dict:
	"""
	Input values of a Geometry Nodes modifier, keyed by their visible name.

	Returns an empty dict when the modifier has no node group assigned, which
	is the state a freshly added Geometry Nodes modifier is in.
	"""
	group = getattr(mod, "node_group", None)
	if group is None:
		return {}

	inputs: dict = {}
	try:
		items = list(group.interface.items_tree)
	except AttributeError:
		# Blender 4.0 and earlier exposed the interface differently. Rather
		# than guess at the old shape, record nothing and let the node group
		# name alone carry the change.
		return {}

	for item in items:
		# items_tree also holds output sockets and panels.
		if getattr(item, "in_out", None) != "INPUT":
			continue
		identifier = getattr(item, "identifier", "")
		if not identifier:
			continue
		inputs[item.name] = _socket_value(mod.get(identifier))
	return inputs


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

		# Geometry Nodes inputs are per node group, so there is no fixed table
		# for them. They are flattened under an "inputs." prefix so each one
		# diffs on its own rather than the whole set changing together.
		if mod.type == "NODES":
			group = getattr(mod, "node_group", None)
			params["node_group"] = group.name if group is not None else None
			for socket_name, value in extract_node_group_inputs(mod).items():
				params[f"inputs.{socket_name}"] = value

		if params:
			entry["params"] = params

		result.append(entry)

	return result