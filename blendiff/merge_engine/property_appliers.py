"""
blendiff.merge_engine.property_appliers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Registry mapping diff property paths to the code that writes them back.

Why a registry
--------------
The applier used to be an ``if/elif`` chain covering six property paths, with
everything else falling through to a debug log. Meanwhile the diff engine
reports property paths across sixteen domains. The result was a merge UI that
let a user resolve a modifier or constraint conflict, reported success, and
applied nothing at all — a silent no-op on exactly the operation where silence
is most dangerous.

Making the mapping data rather than control flow fixes that in two ways:

* ``can_apply`` lets the UI and the merge engine tell, *before* the user
  invests effort, which conflicts are actually applicable — so unsupported
  ones are shown as read-only instead of pretending.
* Adding a diff domain without an applier is now visible: the domain simply
  reports ``supported=False`` everywhere, rather than disappearing.

Each entry owns a matcher and a writer. Writers receive the resolved value and
the live ``bpy`` object, and may raise — the caller records the failure per
property rather than aborting the whole merge.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .armature_applier import REST_BONE_PATH as _REST_BONE_EDIT

from ..data_model.paths import QUOTED_NAME, unescape_name
from ..data_model.schema import VISIBILITY_FLAGS

log = logging.getLogger(__name__)

#: Structural markers the merge engine uses instead of real property paths.
PATH_STRUCTURAL = "__structural__"
PATH_EXISTENCE = "__existence__"
PATH_ADD_ADD = "__add_add__"


@dataclass(frozen=True)
class ApplierEntry:
	"""
	One applicable property path family.

	``batched`` marks paths the Applier handles as a group before per-property
	dispatch — rest bones need a single edit-mode session for the whole object,
	so they cannot be written one attribute at a time. They still belong in the
	registry so that can_apply() reports them as applicable.
	"""

	pattern: re.Pattern
	writer: Callable[..., None]
	description: str
	batched: bool = False

	def matches(self, property_path: str) -> bool:
		return bool(self.pattern.match(property_path))


# Attribute maps
#
# Snapshot keys are chosen for readability in reports and do not always match
# the bpy attribute. These maps are the authoritative translation back.

CAMERA_ATTRS: dict[str, str] = {
	"type": "type",
	"focal_length": "lens",
	"sensor_width": "sensor_width",
	"sensor_fit": "sensor_fit",
	"clip_start": "clip_start",
	"clip_end": "clip_end",
	"ortho_scale": "ortho_scale",
	"shift_x": "shift_x",
	"shift_y": "shift_y",
	# Depth of field lives on a nested struct.
	"dof_use": "dof.use_dof",
	"dof_distance": "dof.focus_distance",
	"dof_fstop": "dof.aperture_fstop",
}

LIGHT_ATTRS: dict[str, str] = {
	"type": "type",
	"color": "color",
	"energy": "energy",
	"use_shadow": "use_shadow",
	"shadow_soft_size": "shadow_soft_size",
	"spot_size": "spot_size",
	"spot_blend": "spot_blend",
	"shape": "shape",
	"size": "size",
	"size_y": "size_y",
	"angle": "angle",
}

PARENT_ATTRS: dict[str, str] = {
	"parent_type": "parent_type",
	"parent_bone": "parent_bone",
}


def _set_nested(target: Any, dotted: str, value: Any) -> None:
	"""Assign through a dotted attribute path such as ``dof.focus_distance``."""
	parts = dotted.split(".")
	for part in parts[:-1]:
		target = getattr(target, part)
	setattr(target, parts[-1], value)


# Writers

def scene_object(context: Any, name: str) -> Any:
	"""
	Find an object by name among the objects of the scene being merged into.

	Not `bpy.data.objects`, which holds every object in the file including
	those linked from a library and those in other scenes. Two datablocks can
	carry the same name when one comes from a library, and `bpy.data.objects`
	returns whichever it finds, so a merge could write to an object the user
	cannot even see. A snapshot only ever records the scene's own objects, so
	the scene is the only place a merge target can legitimately be.
	"""
	import bpy

	scene = getattr(context, "scene", None) or bpy.context.scene
	return scene.objects.get(name)


def _apply_name(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Rename the object.

	A colliding rename silently becomes "Name.001" in Blender, quietly
	diverging from what the merge promised, so a real collision is refused
	rather than allowed to happen.

	Names are unique per library, not per file. A local object and an object
	linked from an asset .blend may both be called "zapBook", so only
	datablocks from the same library as this one can collide with it. Checking
	the whole of `bpy.data.objects` refused perfectly legal renames in any
	file with linked assets, which is most production files: restoring a
	renamed object in the Blender Institute's classroom scene failed on its
	own original name.
	"""
	import bpy

	if not isinstance(value, str) or not value:
		raise ValueError(f"Invalid object name: {value!r}")

	for other in bpy.data.objects:
		if other is obj or other.name != value:
			continue
		if other.library is obj.library:
			raise ValueError(
				f"Cannot rename to {value!r}: an object with that name already "
				f"exists in the same library."
			)
	obj.name = value


def _apply_location(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.location = tuple(value)


def _apply_rotation_euler(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_euler = tuple(value)


def _apply_rotation_quaternion(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_quaternion = tuple(value)


def _apply_rotation_axis_angle(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_axis_angle = tuple(value)


def _apply_rotation_mode(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_mode = str(value)


def _apply_scale(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.scale = tuple(value)


def _apply_visible(obj: Any, path: str, value: Any, context: Any) -> None:
	"""``visible`` is the snapshot's inverted view of hide_viewport."""
	obj.hide_viewport = not bool(value)


def _apply_hide_viewport(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.hide_viewport = bool(value)


def _apply_hide_render(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.hide_render = bool(value)


def _apply_collection_path(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Move the object so it belongs to exactly the named collection."""
	_link_to_collections(obj, [value] if value else [])


def _apply_collection_paths(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Set full collection membership, which may be several collections."""
	_link_to_collections(obj, list(value or []))


def _link_to_collections(obj: Any, paths: list[str]) -> None:
	"""
	Relink an object to exactly the given collections.

	Paths are full ("Scene Collection/Props"); the final segment is the
	collection's name, which is what bpy.data.collections is keyed by.
	"""
	import bpy

	targets = []
	for path in paths:
		name = path.rsplit("/", 1)[-1]
		collection = bpy.data.collections.get(name)
		if collection is None:
			# The scene's root collection is not in bpy.data.collections.
			scene = bpy.context.scene
			if scene and scene.collection and scene.collection.name == name:
				collection = scene.collection
		if collection is None:
			raise ValueError(f"Collection {name!r} not found.")
		targets.append(collection)

	if not targets:
		raise ValueError("Refusing to unlink object from every collection.")

	for collection in list(obj.users_collection):
		collection.objects.unlink(obj)
	for collection in targets:
		collection.objects.link(obj)


_SLOT_INDEX = re.compile(r"material_slots\[(\d+)\]")


def _apply_material_slot(obj: Any, path: str, value: Any, context: Any) -> None:
	import bpy

	match = _SLOT_INDEX.match(path)
	if not match:
		raise ValueError(f"Cannot parse material slot index from {path!r}")
	index = int(match.group(1))

	if index >= len(obj.material_slots):
		raise ValueError(f"{obj.name!r} has no material slot {index}.")

	if value is None:
		obj.material_slots[index].material = None
		return

	material = bpy.data.materials.get(value)
	if material is None:
		raise ValueError(f"Material {value!r} not found.")
	obj.material_slots[index].material = material


def _apply_parent(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Re-parent, preserving the object's world position.

	Setting ``obj.parent`` alone makes the object jump, because its local
	transform is then interpreted relative to the new parent. Capturing the
	world matrix and restoring it afterwards is what the Object > Parent
	operator does, and is what a user merging a parenting change expects.
	"""
	key = path.split(".", 1)[1]

	if key == "parent_name":
		world = obj.matrix_world.copy()
		if value is None:
			obj.parent = None
		else:
			parent = scene_object(context, value)
			if parent is None:
				raise ValueError(f"Parent object {value!r} not found in the scene.")
			if parent is obj:
				raise ValueError("An object cannot be its own parent.")
			obj.parent = parent
		obj.matrix_world = world
		return

	attr = PARENT_ATTRS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported parent property {key!r}")

	world = obj.matrix_world.copy()
	setattr(obj, attr, value if value is not None else "")
	obj.matrix_world = world


def _apply_custom_prop(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Set or delete a user custom property."""
	key = path.split(".", 1)[1]

	if value is None:
		# None means the property was removed in the winning snapshot.
		if key in obj:
			del obj[key]
		return
	obj[key] = value


_POSE_BONE = re.compile(
	r'^pose\.bones\["(?P<bone>' + QUOTED_NAME + r')"\]\.(?P<field>\w+)$'
)

#: Pose-bone fields that can be written back, mapped to their bpy attribute.
POSE_BONE_ATTRS: dict[str, str] = {
	"location": "location",
	"rotation_euler": "rotation_euler",
	"rotation_quaternion": "rotation_quaternion",
	"rotation_axis_angle": "rotation_axis_angle",
	"rotation_mode": "rotation_mode",
	"scale": "scale",
}


def _apply_pose_bone(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one pose-bone transform.

	Pose transforms are the animator's output and are directly settable, unlike
	rest bones, which live on the armature datablock and can only be edited in
	edit mode — see UNSUPPORTED_REASONS.
	"""
	match = _POSE_BONE.match(path)
	if not match:
		raise ValueError(f"Cannot parse pose bone path {path!r}")

	bone_name = unescape_name(match.group("bone"))
	field = match.group("field")

	attr = POSE_BONE_ATTRS.get(field)
	if attr is None:
		raise ValueError(f"Unsupported pose bone property {field!r}")

	pose = getattr(obj, "pose", None)
	if pose is None:
		raise ValueError(f"{obj.name!r} has no pose.")

	pose_bone = pose.bones.get(bone_name)
	if pose_bone is None:
		raise ValueError(f"{obj.name!r} has no pose bone {bone_name!r}.")

	if attr == "rotation_mode":
		setattr(pose_bone, attr, str(value))
	else:
		setattr(pose_bone, attr, tuple(value))


#: Rest-bone properties writable without entering edit mode. The geometry and
#: hierarchy fields are not here — see merge_engine.armature_applier.
REST_BONE_FLAGS: dict[str, str] = {
	"use_deform": "use_deform",
	"use_inherit_rotation": "use_inherit_rotation",
	"inherit_scale": "inherit_scale",
	"envelope_distance": "envelope_distance",
	"envelope_weight": "envelope_weight",
	"hide": "hide",
}

_REST_BONE_FLAG = re.compile(
	r'^armature\.bones\["(?P<bone>' + QUOTED_NAME + r')"\]\.(?P<field>' +
	"|".join(REST_BONE_FLAGS) + r")$"
)

#: Armature datablock settings, writable in object mode.
ARMATURE_SETTINGS: dict[str, str] = {
	"pose_position": "pose_position",
	"display_type": "display_type",
}


def _apply_rest_bone_flag(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Set a rest-bone flag that does not require edit mode.

	Deform and inheritance flags change how a rig behaves without moving
	anything, which makes them easy to break unnoticed and worth merging.
	"""
	match = _REST_BONE_FLAG.match(path)
	if not match:
		raise ValueError(f"Cannot parse rest bone path {path!r}")

	if obj.data is None:
		raise ValueError(f"{obj.name!r} has no armature data.")

	bone = obj.data.bones.get(unescape_name(match.group("bone")))
	if bone is None:
		raise ValueError(f"{obj.name!r} has no bone {match.group('bone')!r}.")

	attr = REST_BONE_FLAGS[match.group("field")]
	current = getattr(bone, attr)
	setattr(bone, attr, type(current)(value) if isinstance(current, bool) else value)


def _apply_armature_setting(obj: Any, path: str, value: Any, context: Any) -> None:
	key = path.split(".", 1)[1]
	attr = ARMATURE_SETTINGS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported armature property {key!r}")
	if obj.data is None:
		raise ValueError(f"{obj.name!r} has no armature data.")
	setattr(obj.data, attr, value)


def _batched_elsewhere(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Placeholder writer for paths the Applier batches.

	Reaching this means per-property dispatch was handed something the batch
	phase should already have consumed, which is a bug rather than a user
	error.
	"""
	raise RuntimeError(f"{path!r} must be applied by the batched rest-bone pass")


def _apply_camera(obj: Any, path: str, value: Any, context: Any) -> None:
	key = path.split(".", 1)[1]
	attr = CAMERA_ATTRS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported camera property {key!r}")
	if obj.data is None:
		raise ValueError(f"{obj.name!r} has no camera data.")
	_set_nested(obj.data, attr, value)


def _apply_light(obj: Any, path: str, value: Any, context: Any) -> None:
	key = path.split(".", 1)[1]
	attr = LIGHT_ATTRS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported light property {key!r}")
	if obj.data is None:
		raise ValueError(f"{obj.name!r} has no light data.")
	_set_nested(obj.data, attr, value)


#: modifiers[3].levels -> index 3, key "levels"
#
# `.type` is excluded so it stays unapplicable and reports its reason. Matching
# it here would make can_apply() claim the merge can retype a modifier, and the
# write would then fail at apply time instead of being skipped cleanly.
_MODIFIER_PROP = re.compile(
	r"^modifiers\[(\d+)\]\.(?!type$|node_group$)([A-Za-z_][\w.]*)$"
)

#: Fields every modifier has, named identically in the snapshot and in bpy.
_MODIFIER_COMMON = ("name", "show_viewport", "show_render")


def _modifier_param_attr(mod_type: str, key: str) -> Optional[str]:
	"""
	bpy attribute behind a snapshot param key, for one modifier type.

	Built from the extractor's own table so the two cannot drift: it records
	(bpy_attr, snapshot_key) per type, and this reads it backwards. Looking the
	key up against the *live* modifier's type is also the type guard. If the
	modifier in the scene is not the type the snapshot described, its keys will
	not be in that type's table and the write is refused instead of setting
	some unrelated attribute.
	"""
	from ..extractor.modifier_extractor import _MOD_PROPS

	for bpy_attr, output_key in _MOD_PROPS.get(mod_type, []):
		if output_key == key:
			return bpy_attr
	return None


def _apply_modifier(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one setting on an existing modifier.

	Only settings on a modifier that is already there. Adding, removing,
	retyping and reordering stay unapplicable on purpose: the snapshot records
	an added modifier as the single string "SUBSURF(Subdivision)" with no
	parameters, so creating one from that would silently give it defaults and
	report success. Reporting it and letting the user add it is honest; writing
	the wrong thing is not.
	"""
	match = _MODIFIER_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported modifier property {path!r}")

	index, key = int(match.group(1)), match.group(2)
	if index >= len(obj.modifiers):
		raise ValueError(
			f"{obj.name!r} has no modifier at slot {index}; the stack differs "
			f"from the snapshot."
		)
	mod = obj.modifiers[index]

	if key in _MODIFIER_COMMON:
		setattr(mod, key, value)
		return

	if key.startswith(_NODE_INPUT_PREFIX):
		_apply_node_input(mod, key[len(_NODE_INPUT_PREFIX):], value, context)
		return

	if key == "object_name":
		# The parameter holds an object reference, stored as a name.
		if value is None:
			mod.object = None
			return
		target = scene_object(context, value)
		if target is None:
			raise ValueError(f"Modifier target {value!r} not found in the scene.")
		mod.object = target
		return

	attr = _modifier_param_attr(mod.type, key)
	if attr is None:
		raise ValueError(
			f"{key!r} is not a known setting of a {mod.type} modifier; "
			f"slot {index} is {mod.type} in this scene."
		)
	setattr(mod, attr, value)


def _apply_visibility_flag(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one of the display or ray visibility switches.

	These are plain attributes on the object, so the write is direct. They are
	guarded by the same existence check the extractor uses: the ray visibility
	flags come from Cycles and are not present on every build, and setting an
	attribute that is not there would create a stray Python attribute that
	looks applied and does nothing.
	"""
	if not hasattr(obj, path):
		raise ValueError(
			f"{obj.name!r} has no {path!r}; this Blender build does not expose it."
		)
	current = getattr(obj, path)
	setattr(obj, path, value if isinstance(current, str) else bool(value))


#: Keys holding a datablock reference rather than a value. Writing a name
#: string into one would raise, so they are reported instead: pointing a
#: curve at a different taper object is a modelling decision, not a setting.
_OBJECT_DATA_REFERENCES = ("taper_object", "bevel_object", "font", "sound")

def _apply_vertex_positions(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Put a mesh back to the shape a snapshot recorded.

	Positions are written into the existing mesh rather than the mesh being
	rebuilt. Rebuilding means clearing the geometry first, and that destroys
	everything hanging off it: on a sphere with UVs and a vertex group,
	clearing and rebuilding left uv=0 and vgroups=0 while writing positions
	left both intact.

	Writing in place only works while the topology is the one those positions
	belong to, so the vertex count has to match exactly. A snapshot taken
	before a re-mesh cannot be applied to the re-meshed object, and refusing
	is the only honest answer: the alternative is a mesh with its vertices
	moved to positions that meant something on different geometry.
	"""
	from ..extractor.geometry_store import decode_positions

	mesh = getattr(obj, "data", None)
	if mesh is None or not hasattr(mesh, "vertices"):
		raise ValueError(f"{obj.name!r} has no mesh to put positions into.")

	coordinates = decode_positions(value)
	expected = len(mesh.vertices) * 3
	if len(coordinates) != expected:
		raise ValueError(
			f"{obj.name!r} has {len(mesh.vertices)} vertices but the snapshot "
			f"stored {len(coordinates) // 3}; the topology changed, so the "
			f"positions cannot be put back."
		)

	mesh.vertices.foreach_set("co", coordinates)
	mesh.update()


# Constraints
#
# The same shape as modifiers: a stack of slots, each with a type, a name, a
# couple of common switches and a set of type-specific parameters. The
# applier mirrors the modifier one deliberately, including what it refuses.
#
# Pose bone constraints run through the same writer. A bone's stack is
# identical to an object's, which is why the extractor and the diff already
# share their code, and an IK or Copy Rotation change is the edit most likely
# to break a rig and most worth merging.

#: constraints[2].influence
_CONSTRAINT_PROP = re.compile(
	r"^constraints\[(\d+)\]\.(?!type$)([A-Za-z_]\w*)$"
)

#: pose.bones["Head"].constraints[0].influence
_BONE_CONSTRAINT_PROP = re.compile(
	r'^pose\.bones\["' + QUOTED_NAME + r'"\]\.constraints\[(\d+)\]\.'
	r"(?!type$)([A-Za-z_]\w*)$"
)

#: Fields every constraint has, whatever its type.
#
# "enabled" is the snapshot's name for the inverse of bpy's `mute`, because a
# report saying a constraint was enabled reads better than one saying it was
# un-muted. The inversion happens here rather than being pushed onto readers.
_CONSTRAINT_COMMON = {"name", "enabled", "influence"}


def _constraint_param_attr(constraint_type: str, key: str) -> Optional[str]:
	"""
	bpy attribute behind a snapshot param key, for one constraint type.

	Read backwards out of the extractor's own table so the two cannot drift.
	Looking the key up against the *live* constraint's type doubles as the
	type guard: if the slot now holds a different kind of constraint, its keys
	will not be in that type's table and the write is refused.
	"""
	from ..extractor.constraint_extractor import _CONSTRAINT_PROPS

	for bpy_attr, output_key in _CONSTRAINT_PROPS.get(constraint_type, []):
		if output_key == key:
			return bpy_attr
	return None


def _write_constraint(con: Any, key: str, value: Any, context: Any) -> None:
	"""Write one setting on a constraint that already exists."""
	if key == "name":
		con.name = value
		return
	if key == "enabled":
		con.mute = not bool(value)
		return
	if key == "influence":
		con.influence = float(value)
		return

	attr = _constraint_param_attr(con.type, key)
	if attr is None:
		raise ValueError(
			f"{key!r} is not a known setting of a {con.type} constraint; "
			f"this slot is {con.type} in this scene."
		)

	# A constraint's target is an object, stored by name. subtarget is a bone
	# name and stays a plain string.
	if attr == "target":
		if value is None:
			con.target = None
			return
		target = scene_object(context, value)
		if target is None:
			raise ValueError(f"Constraint target {value!r} not found in the scene.")
		con.target = target
		return

	setattr(con, attr, value)


def _constraint_at(stack: Any, index: int, owner: str) -> Any:
	"""One slot of a constraint stack, or a refusal naming what is there."""
	if index >= len(stack):
		raise ValueError(
			f"{owner} has no constraint at slot {index}; the stack differs "
			f"from the snapshot."
		)
	return stack[index]


def _apply_constraint(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one setting on an existing object constraint.

	Adding, removing and retyping stay unapplicable for the same reason they
	do for modifiers: the snapshot records an added constraint as a name and a
	type with no parameters, so building one from that would quietly give it
	defaults and report success.
	"""
	match = _CONSTRAINT_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported constraint property {path!r}")

	index, key = int(match.group(1)), match.group(2)
	con = _constraint_at(obj.constraints, index, repr(obj.name))
	_write_constraint(con, key, value, context)


def _apply_bone_constraint(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Write one setting on an existing pose bone constraint."""
	match = _BONE_CONSTRAINT_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported bone constraint property {path!r}")

	bone_name = unescape_name(match.group(1))
	index, key = int(match.group(2)), match.group(3)

	pose = getattr(obj, "pose", None)
	if pose is None:
		raise ValueError(f"{obj.name!r} has no pose; it is not an armature.")
	bone = pose.bones.get(bone_name)
	if bone is None:
		raise ValueError(f"{obj.name!r} has no pose bone named {bone_name!r}.")

	con = _constraint_at(bone.constraints, index, f"bone {bone_name!r}")
	_write_constraint(con, key, value, context)


#: data.bevel_depth, data.body, data.display_size and so on.
#
# The reference keys are excluded rather than rejected inside the writer, so
# can_apply() tells the truth about them and the merge UI shows the reason
# instead of offering a choice it would then fail to honour.
_OBJECT_DATA_PROP = re.compile(
	r"^data\.(?!(?:" + "|".join(_OBJECT_DATA_REFERENCES) + r")$)([a-z_]+)$"
)


def _apply_object_data(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one type-specific setting: a curve's bevel, a text body, and so on.

	Empties keep their settings on the object rather than in a datablock,
	which is why the target is chosen by type rather than always being
	obj.data.
	"""
	match = _OBJECT_DATA_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported object data property {path!r}")

	key = match.group(1)

	if getattr(obj, "type", None) == "EMPTY":
		target, attr = obj, f"empty_{key}" if key in ("display_type", "display_size", "image_depth") else key
	else:
		target, attr = getattr(obj, "data", None), key

	if target is None:
		raise ValueError(f"{obj.name!r} has no data to write {key!r} to.")
	if not hasattr(target, attr):
		raise ValueError(
			f"{obj.name!r} has no {attr!r}; its type differs from the snapshot."
		)
	setattr(target, attr, value)


#: mesh.shape_keys["Smile"].value -> key "Smile", setting "value"
#
# Only the settings that are a plain write. Matching every field would make
# can_apply() claim BlenDiff can restore a sculpted shape or rewire a key's
# relative base, and the write would then fail at apply time instead of being
# skipped with a reason.
_SHAPE_KEY_PROP = re.compile(
	r'^mesh\.shape_keys\["' + QUOTED_NAME + r'"\]\.'
	r'(value|mute|slider_min|slider_max|interpolation)$'
)

#: Shape key settings that are a plain write. "shape" is the point positions,
#: which are hashed rather than stored and so can never be written back.
_SHAPE_KEY_WRITABLE = {
	"value": float,
	"mute": bool,
	"slider_min": float,
	"slider_max": float,
	"interpolation": str,
}


def _apply_shape_key(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one setting on an existing shape key.

	Sliding a key is the most common thing anyone does with one and the most
	likely thing for two people to disagree about, so it is worth merging even
	though the shape itself cannot be.

	Keys are found by name rather than index: reordering them changes nothing
	about what they do, and pairing by position would write to the wrong key
	after an insertion.
	"""
	match = _SHAPE_KEY_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported shape key property {path!r}")

	key_name = unescape_name(match.group(1))
	field = match.group(2)
	coerce = _SHAPE_KEY_WRITABLE.get(field)
	if coerce is None:
		raise ValueError(f"Shape key setting {field!r} cannot be written back")

	mesh = getattr(obj, "data", None)
	keys = getattr(mesh, "shape_keys", None) if mesh is not None else None
	if keys is None:
		raise ValueError(f"{obj.name!r} has no shape keys.")

	block = keys.key_blocks.get(key_name)
	if block is None:
		raise ValueError(f"{obj.name!r} has no shape key named {key_name!r}.")

	# slider_min and slider_max bound value, and Blender clamps a write that
	# falls outside the current range. Widening the range first is not this
	# applier's business, so a clamped write is reported rather than hidden.
	setattr(block, field, coerce(value))
	written = getattr(block, field)
	if coerce is float and abs(float(written) - float(value)) > 1e-5:
		raise ValueError(
			f"{key_name!r}.{field} was clamped to {written} by its slider "
			f"range; widen the range first."
		)


#: Geometry Nodes input keys are flattened as "inputs.<visible socket name>".
_NODE_INPUT_PREFIX = "inputs."

#: Socket types that hold a datablock rather than a plain value.
_ID_SOCKETS = frozenset((
	"NodeSocketObject",
	"NodeSocketMaterial",
	"NodeSocketCollection",
	"NodeSocketImage",
))


def _resolve_id_socket(socket_type: str, name: str, context: Any) -> Any:
	"""
	Find the datablock an ID-valued input refers to, by name.

	Object sockets resolve within the scene, for the same reason merge targets
	do: a library object sharing a name would otherwise win. The others are
	file-wide collections with no scene-level equivalent.
	"""
	import bpy

	if socket_type == "NodeSocketObject":
		return scene_object(context, name)
	if socket_type == "NodeSocketMaterial":
		return bpy.data.materials.get(name)
	if socket_type == "NodeSocketCollection":
		return bpy.data.collections.get(name)
	if socket_type == "NodeSocketImage":
		return bpy.data.images.get(name)
	return None


def _node_input_socket(group: Any, socket_name: str):
	"""The interface item for one input, by its visible name."""
	for item in group.interface.items_tree:
		if getattr(item, "in_out", None) == "INPUT" and item.name == socket_name:
			return item
	return None


def _apply_node_input(mod: Any, socket_name: str, value: Any, context: Any) -> None:
	"""
	Write one Geometry Nodes input.

	Inputs live on the modifier as IDProperties keyed by an opaque identifier
	("Socket_3"), while the name the snapshot records is the one the artist
	sees. The node group's interface is the only thing that maps between them,
	so a write is only possible while the same group is assigned.
	"""
	group = getattr(mod, "node_group", None)
	if group is None:
		raise ValueError(
			f"{mod.name!r} has no node group assigned, so {socket_name!r} "
			f"cannot be set."
		)

	item = _node_input_socket(group, socket_name)
	if item is None:
		raise ValueError(
			f"Node group {group.name!r} has no input named {socket_name!r}; "
			f"it differs from the one the snapshot recorded."
		)

	socket_type = getattr(item, "socket_type", "")
	if socket_type in _ID_SOCKETS:
		if value is None:
			mod[item.identifier] = None
			return
		target = _resolve_id_socket(socket_type, value, context)
		if target is None:
			raise ValueError(f"{socket_type} input {socket_name!r}: {value!r} not found.")
		mod[item.identifier] = target
		return

	mod[item.identifier] = value


def _apply_modifier_order(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Reorder the modifier stack to the recorded order of names.

	Order is the whole point of a modifier stack: a Bevel before a Subsurf and
	a Bevel after it give different meshes, so a merge that applied every
	setting but left the order alone would be quietly wrong.

	The names must be exactly the ones present. The diff only reports an order
	change when both sides hold the same set of modifiers, so a mismatch here
	means the live stack has moved on from both snapshots, and reordering what
	is there now would be guesswork.
	"""
	target = [str(name) for name in value or []]
	current = [mod.name for mod in obj.modifiers]

	if sorted(target) != sorted(current):
		raise ValueError(
			f"{obj.name!r} has modifiers {current}, but the snapshot recorded "
			f"{target}; reorder it by hand."
		)

	# Walk each name to its slot. Stacks are a handful of entries, so the
	# repeated scan costs nothing worth avoiding.
	for index, name in enumerate(target):
		position = [mod.name for mod in obj.modifiers].index(name)
		if position != index:
			obj.modifiers.move(position, index)


# Material node graphs
#
# Only an input value on a node that exists on both sides, and the image a
# texture node points at. Those are the two things anyone actually tweaks
# after a graph is built, and both are a single assignment.
#
# Adding, removing or retyping a node stays out: the snapshot records a node's
# type and input values but not its node-specific settings, so BlenDiff would
# create a node that looked right and behaved differently. Rewiring stays out
# because a link is only meaningful alongside the nodes it joins, and applying
# half a rewire leaves a graph that renders nothing.

_MATERIAL_NODE = r'^materials\["' + QUOTED_NAME + r'"\]\.nodes\["' + QUOTED_NAME + r'"\]'

_MATERIAL_NODE_INPUT = re.compile(
	_MATERIAL_NODE + r'\.inputs\["' + QUOTED_NAME + r'"\]$'
)

_MATERIAL_NODE_IMAGE = re.compile(_MATERIAL_NODE + r'\.image$')


def _material_node(obj: Any, material_name: str, node_name: str) -> Any:
	"""
	Find one node of one of this object's materials.

	The material is looked up in the object's own slots rather than in
	bpy.data.materials: a file can hold several materials with names that only
	differ by a numeric suffix, and writing to one the object does not use
	would change some other object's look while appearing to succeed here.
	"""
	for slot in obj.material_slots:
		mat = slot.material
		if mat is not None and mat.name == material_name:
			break
	else:
		raise ValueError(f"{obj.name!r} has no material named {material_name!r}.")

	if not mat.use_nodes or mat.node_tree is None:
		raise ValueError(
			f"Material {material_name!r} has no node tree, so {node_name!r} "
			f"does not exist in it."
		)

	node = mat.node_tree.nodes.get(node_name)
	if node is None:
		raise ValueError(
			f"Material {material_name!r} has no node named {node_name!r}; its "
			f"graph differs from the one the snapshot recorded."
		)
	return node


def _socket_value(socket: Any, value: Any) -> Any:
	"""Coerce a recorded socket value back to what default_value accepts."""
	kind = getattr(socket, "type", "")

	if kind == "VALUE":
		return float(value)
	if kind == "INT":
		return int(value)
	if kind == "BOOLEAN":
		return bool(value)
	if kind == "STRING":
		return str(value)

	if kind in ("RGBA", "RGB", "VECTOR"):
		components = list(value)
		expected = len(socket.default_value)
		if len(components) != expected:
			raise ValueError(
				f"{socket.name!r} takes {expected} components, but the "
				f"snapshot recorded {len(components)}."
			)
		return components

	return value


def _apply_material_node_input(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Write one input value on an existing node of one of this object's materials."""
	match = _MATERIAL_NODE_INPUT.match(path)
	if match is None:
		raise ValueError(f"Unsupported material node property {path!r}")

	material_name, node_name, socket_name = (
		unescape_name(group) for group in match.groups()
	)
	node = _material_node(obj, material_name, node_name)

	# A node's input names are not unique: a Math node has three sockets all
	# called "Value". The extractor keys inputs by name, so it only ever kept
	# the last of those, and there is no way back from the name to the socket
	# the change came from. Refusing beats a one-in-three guess that silently
	# rewires the maths.
	sockets = [sock for sock in node.inputs if sock.name == socket_name]
	if not sockets:
		raise ValueError(
			f"Node {node_name!r} has no input named {socket_name!r}; its type "
			f"or version differs from the one recorded."
		)
	if len(sockets) > 1:
		raise ValueError(
			f"Node {node_name!r} has {len(sockets)} inputs named "
			f"{socket_name!r}, so which one changed cannot be told apart; set "
			f"it by hand."
		)

	socket = sockets[0]
	if not hasattr(socket, "default_value"):
		raise ValueError(f"Input {socket_name!r} holds no value that can be written.")

	if socket.is_linked:
		raise ValueError(
			f"Input {socket_name!r} is linked to another node, so its value "
			f"comes from that link and writing one would change nothing."
		)

	if value is None:
		raise ValueError(
			f"The snapshot recorded no value for {socket_name!r}, so there is "
			f"nothing to write."
		)

	socket.default_value = _socket_value(socket, value)


def _apply_material_node_image(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Point a texture node at an image datablock by name."""
	import bpy

	match = _MATERIAL_NODE_IMAGE.match(path)
	if match is None:
		raise ValueError(f"Unsupported material node property {path!r}")

	material_name, node_name = (unescape_name(group) for group in match.groups())
	node = _material_node(obj, material_name, node_name)

	if not hasattr(node, "image"):
		raise ValueError(
			f"Node {node_name!r} is a {getattr(node, 'type', '?')} node and "
			f"holds no image."
		)

	if value is None:
		node.image = None
		return

	image = bpy.data.images.get(str(value))
	if image is None:
		raise ValueError(
			f"No image named {value!r} in this file; load it first, then apply "
			f"this change."
		)
	node.image = image


# Drivers
#
# Three fields, each a single assignment on the driver of an existing driven
# FCurve: what kind of driver it is, the expression it evaluates and whether
# that expression can see the driven object as "self".
#
# Variables stay out. The diff reports only their names, because the full
# list is compared as a whole, so there is nothing to write from. Rebuilding
# one would also mean resolving its targets' datablocks and id_types, which is
# creating a driver rather than merging a change to one.

_DRIVER_PROP = re.compile(
	r'^drivers\["' + QUOTED_NAME + r'"\]\[(\d+)\]\.'
	r'(driver_type|expression|use_self)$'
)

#: Snapshot key -> the attribute on bpy.types.Driver. "driver_type" is called
#: "type" there; the snapshot spells it out so reports read plainly.
_DRIVER_ATTRS = {
	"driver_type": "type",
	"expression": "expression",
	"use_self": "use_self",
}


def _apply_driver(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Write one field of an existing driver."""
	match = _DRIVER_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported driver property {path!r}")

	data_path = unescape_name(match.group(1))
	array_index = int(match.group(2))
	field = match.group(3)

	anim = getattr(obj, "animation_data", None)
	if anim is None:
		raise ValueError(f"{obj.name!r} has no animation data, so it has no drivers.")

	fcurve = anim.drivers.find(data_path, index=array_index)
	if fcurve is None:
		raise ValueError(
			f"{obj.name!r} has no driver on {data_path!r}[{array_index}]; it "
			f"differs from the one the snapshot recorded."
		)

	driver = fcurve.driver
	if field == "expression":
		# A SCRIPTED driver is the only kind that evaluates an expression, and
		# the extractor records "" for the others. Writing that empty string
		# over a working expression because the driver type also changed in
		# the same merge would quietly break the rig.
		if driver.type != "SCRIPTED" and not value:
			raise ValueError(
				f"The driver on {data_path!r}[{array_index}] is "
				f"{driver.type}, which evaluates no expression."
			)
		driver.expression = str(value or "")
		return

	if field == "use_self":
		driver.use_self = bool(value)
		return

	driver.type = str(value)


# Scene-level settings
#
# Render settings, units, markers, the world and the scene's own custom
# properties. These were diffed from early on, built into a merge proposal,
# and then skipped at apply time with "scene changes must be applied
# manually" — so two people bumping the sample count or changing the output
# path were shown the collision and left to fix it by hand. Almost all of it
# is a single assignment somewhere under the scene.
#
# Scene paths arrive with a "scene." prefix. The merge engine already uses
# that prefix when asking whether a scene change is applicable, so writing
# the entries this way means can_apply and the writers agree on one spelling
# rather than two.

#: Render snapshot key -> dotted path from the scene it lives at.
#
# The snapshot flattens several structs into one dict, so this map is the way
# back. It mirrors render_extractor.py and has to be kept in step with it.
SCENE_RENDER_TARGETS: dict[str, str] = {
	"engine": "render.engine",
	"resolution_x": "render.resolution_x",
	"resolution_y": "render.resolution_y",
	"resolution_percentage": "render.resolution_percentage",
	"filepath": "render.filepath",
	"file_format": "render.image_settings.file_format",
	"color_mode": "render.image_settings.color_mode",
	"color_depth": "render.image_settings.color_depth",
	"frame_start": "frame_start",
	"frame_end": "frame_end",
	"frame_step": "frame_step",
	"fps": "render.fps",
	"fps_base": "render.fps_base",
	"display_device": "display_settings.display_device",
	"view_transform": "view_settings.view_transform",
	"look": "view_settings.look",
	"exposure": "view_settings.exposure",
	"gamma": "view_settings.gamma",
}

#: World snapshot key -> dotted path from the world datablock.
SCENE_WORLD_TARGETS: dict[str, str] = {
	"color": "color",
	"ao_factor": "light_settings.ao_factor",
	"ao_distance": "light_settings.distance",
}

#: use_ao is spelled differently across versions, so it is tried by name.
_WORLD_AO_NAMES = ("use_ambient_occlusion", "use_ao")

# The render snapshot is one flat dict under "render", so its paths read
# scene.render.resolution_x even for frame_end, which lives on the scene
# itself. The target map above is what untangles that.
_SCENE_RENDER_PROP = re.compile(
	r"^scene\.render\.("
	+ "|".join(re.escape(key) for key in SCENE_RENDER_TARGETS)
	+ r")$"
)

_SCENE_ENGINE_PROP = re.compile(r"^scene\.render\.(cycles|eevee)\.(\w+)$")

_SCENE_UNIT_PROP = re.compile(r"^scene\.units\.(\w+)$")

_SCENE_MARKER = re.compile(r'^scene\.markers\["' + QUOTED_NAME + r'"\]$')

_SCENE_MARKER_FIELD = re.compile(
	r'^scene\.markers\["' + QUOTED_NAME + r'"\]\.(frame|camera)$'
)

_SCENE_CUSTOM_PROP = re.compile(r"^scene\.custom_props\.[^.]+$")

_SCENE_WORLD_PROP = re.compile(
	r"^scene\.world\.(" + "|".join(SCENE_WORLD_TARGETS) + r"|use_ao)$"
)

_SCENE_WORLD_BACKGROUND = re.compile(
	r"^scene\.world\.(background_color|background_strength)$"
)


def _scene_of(context: Any) -> Any:
	"""The scene being merged into."""
	import bpy

	scene = getattr(context, "scene", None) or bpy.context.scene
	if scene is None:
		raise ValueError("There is no active scene to write to.")
	return scene


def _apply_scene_render(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Write one render or colour-management setting."""
	match = _SCENE_RENDER_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")
	_set_nested(_scene_of(context), SCENE_RENDER_TARGETS[match.group(1)], value)


def _apply_scene_engine(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write one Cycles or EEVEE setting.

	Both are checked rather than assumed: Cycles can be disabled as an
	add-on, and EEVEE's settings were rewritten in 4.2, so a file snapshotted
	on an older Blender carries keys this one has never heard of. Writing to a
	missing struct or attribute would raise an unhelpful AttributeError from
	deep inside the applier instead of saying which setting is not here.
	"""
	import bpy

	match = _SCENE_ENGINE_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")

	engine, key = match.group(1), match.group(2)
	settings = getattr(_scene_of(context), engine, None)
	if settings is None:
		raise ValueError(
			f"This Blender has no {engine} settings, so {key!r} cannot be set."
		)
	if not hasattr(settings, key):
		raise ValueError(
			f"{engine}.{key} does not exist in Blender "
			f"{bpy.app.version_string}; the snapshot came from a version that "
			f"had it."
		)
	setattr(settings, key, value)


def _apply_scene_units(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Write one unit setting."""
	import bpy

	match = _SCENE_UNIT_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")

	attr = match.group(1)
	units = _scene_of(context).unit_settings
	if not hasattr(units, attr):
		raise ValueError(
			f"Unit setting {attr!r} does not exist in Blender "
			f"{bpy.app.version_string}."
		)
	setattr(units, attr, value)


def _apply_scene_marker(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Add, move or remove one timeline marker.

	Unlike an object, a marker is fully described by what the snapshot holds:
	a name and a frame. There is nothing to guess, so creating one is a real
	merge rather than a fabrication, which is why this is the one structural
	change BlenDiff does apply.
	"""
	match = _SCENE_MARKER.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")

	name = unescape_name(match.group(1))
	scene = _scene_of(context)
	existing = scene.timeline_markers.get(name)

	if value is None:
		if existing is not None:
			scene.timeline_markers.remove(existing)
		return

	if existing is not None:
		existing.frame = int(value)
		return
	scene.timeline_markers.new(name, frame=int(value))


def _apply_scene_marker_field(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Move a marker, or change which camera it binds."""
	match = _SCENE_MARKER_FIELD.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")

	name = unescape_name(match.group(1))
	field = match.group(2)
	scene = _scene_of(context)

	marker = scene.timeline_markers.get(name)
	if marker is None:
		raise ValueError(
			f"This scene has no marker named {name!r}; it was removed since "
			f"the snapshot."
		)

	if field == "frame":
		marker.frame = int(value)
		return

	if value is None:
		marker.camera = None
		return

	camera = scene_object(context, str(value))
	if camera is None:
		raise ValueError(
			f"Marker {name!r} binds camera {value!r}, which is not in this "
			f"scene."
		)
	marker.camera = camera


def _apply_scene_custom_prop(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Set or delete one of the scene's own custom properties."""
	key = path.split(".", 2)[2]
	scene = _scene_of(context)

	if value is None:
		if key in scene:
			del scene[key]
		return
	scene[key] = value


def _world_of(context: Any) -> Any:
	world = _scene_of(context).world
	if world is None:
		raise ValueError(
			"This scene has no world, so there are no world settings to write."
		)
	return world


def _apply_scene_world(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Write one plain world setting."""
	match = _SCENE_WORLD_PROP.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")

	key = match.group(1)
	world = _world_of(context)

	if key == "use_ao":
		for name in _WORLD_AO_NAMES:
			if hasattr(world.light_settings, name):
				setattr(world.light_settings, name, bool(value))
				return
		raise ValueError(
			"This Blender's world has no ambient occlusion toggle under either "
			"name BlenDiff knows."
		)

	_set_nested(world, SCENE_WORLD_TARGETS[key], value)


def _apply_scene_world_background(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Write the Background node's colour or strength.

	The snapshot flattens these out of the world's node tree because they are
	what people mean by "the sky", so writing them back means going into that
	tree. Anything beyond the one Background node, an HDRI image or a rewired
	graph, stays out for the same reason a material's does.
	"""
	match = _SCENE_WORLD_BACKGROUND.match(path)
	if match is None:
		raise ValueError(f"Unsupported scene property {path!r}")

	key = match.group(1)
	world = _world_of(context)
	if not world.use_nodes or world.node_tree is None:
		raise ValueError(
			"This world uses a flat colour rather than nodes; set world.color "
			"instead."
		)

	node = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
	if node is None:
		raise ValueError(
			"This world's node tree has no Background node, so there is "
			"nothing to write this to."
		)

	socket_name = "Color" if key == "background_color" else "Strength"
	socket = node.inputs.get(socket_name)
	if socket is None:
		raise ValueError(f"The Background node has no {socket_name!r} input.")
	if socket.is_linked:
		raise ValueError(
			f"The Background node's {socket_name!r} comes from another node, "
			f"an HDRI for instance, so writing a value would change nothing."
		)
	if value is None:
		raise ValueError(
			f"The snapshot recorded no {socket_name!r}, so there is nothing to "
			f"write."
		)
	socket.default_value = _socket_value(socket, value)


# Registry
#
# Order matters only in that the first match wins; patterns are disjoint.

REGISTRY: tuple[ApplierEntry, ...] = (
	ApplierEntry(re.compile(r"^name$"), _apply_name, "Object name"),
	ApplierEntry(re.compile(r"^transform\.location$"), _apply_location, "Location"),
	ApplierEntry(re.compile(r"^transform\.rotation_euler$"), _apply_rotation_euler, "Euler rotation"),
	ApplierEntry(re.compile(r"^transform\.rotation_quaternion$"), _apply_rotation_quaternion, "Quaternion rotation"),
	ApplierEntry(re.compile(r"^transform\.rotation_axis_angle$"), _apply_rotation_axis_angle, "Axis-angle rotation"),
	ApplierEntry(re.compile(r"^transform\.rotation_mode$"), _apply_rotation_mode, "Rotation mode"),
	ApplierEntry(re.compile(r"^transform\.scale$"), _apply_scale, "Scale"),
	ApplierEntry(re.compile(r"^visible$"), _apply_visible, "Viewport visibility"),
	ApplierEntry(re.compile(r"^hide_viewport$"), _apply_hide_viewport, "Viewport visibility"),
	ApplierEntry(re.compile(r"^hide_render$"), _apply_hide_render, "Render visibility"),
	ApplierEntry(
		re.compile("^(" + "|".join(VISIBILITY_FLAGS) + ")$"),
		_apply_visibility_flag,
		"Display or ray visibility",
	),
	ApplierEntry(re.compile(r"^collection_path$"), _apply_collection_path, "Collection"),
	ApplierEntry(re.compile(r"^collection_paths$"), _apply_collection_paths, "Collection membership"),
	ApplierEntry(re.compile(r"^material_slots\[\d+\](\.name)?$"), _apply_material_slot, "Material slot"),
	ApplierEntry(re.compile(r"^parent\.(parent_name|parent_type|parent_bone)$"), _apply_parent, "Parenting"),
	ApplierEntry(re.compile(r"^custom_props\.[^.]+$"), _apply_custom_prop, "Custom property"),
	ApplierEntry(_POSE_BONE, _apply_pose_bone, "Pose bone transform"),
	ApplierEntry(_REST_BONE_FLAG, _apply_rest_bone_flag, "Bone flag"),
	ApplierEntry(
		re.compile(r"^armature\.(pose_position|display_type)$"),
		_apply_armature_setting, "Armature setting",
	),
	# Applied as a group in a single edit-mode session, not one at a time.
	ApplierEntry(
		_REST_BONE_EDIT, _batched_elsewhere, "Bone rest pose", batched=True,
	),
	ApplierEntry(re.compile(r"^camera\.[^.]+$"), _apply_camera, "Camera data"),
	ApplierEntry(re.compile(r"^light\.[^.]+$"), _apply_light, "Light data"),
	ApplierEntry(
		re.compile(r"^mesh\.stored_geometry$"),
		_apply_vertex_positions, "Mesh vertex positions",
	),
	ApplierEntry(_OBJECT_DATA_PROP, _apply_object_data, "Object data"),
	ApplierEntry(_CONSTRAINT_PROP, _apply_constraint, "Constraint setting"),
	ApplierEntry(_BONE_CONSTRAINT_PROP, _apply_bone_constraint, "Bone constraint setting"),
	ApplierEntry(_MODIFIER_PROP, _apply_modifier, "Modifier setting"),
	ApplierEntry(re.compile(r"^modifiers\.order$"), _apply_modifier_order, "Modifier order"),
	ApplierEntry(_SHAPE_KEY_PROP, _apply_shape_key, "Shape key setting"),
	ApplierEntry(_MATERIAL_NODE_INPUT, _apply_material_node_input, "Material node input"),
	ApplierEntry(_MATERIAL_NODE_IMAGE, _apply_material_node_image, "Texture node image"),
	ApplierEntry(_DRIVER_PROP, _apply_driver, "Driver setting"),
	ApplierEntry(_SCENE_RENDER_PROP, _apply_scene_render, "Render setting"),
	ApplierEntry(_SCENE_ENGINE_PROP, _apply_scene_engine, "Render engine setting"),
	ApplierEntry(_SCENE_UNIT_PROP, _apply_scene_units, "Unit setting"),
	ApplierEntry(_SCENE_MARKER_FIELD, _apply_scene_marker_field, "Timeline marker"),
	ApplierEntry(_SCENE_MARKER, _apply_scene_marker, "Timeline marker"),
	ApplierEntry(_SCENE_CUSTOM_PROP, _apply_scene_custom_prop, "Scene custom property"),
	ApplierEntry(_SCENE_WORLD_BACKGROUND, _apply_scene_world_background, "World background"),
	ApplierEntry(_SCENE_WORLD_PROP, _apply_scene_world, "World setting"),
)


# Paths that are genuinely not applicable, with the reason shown to the user.
# Being explicit here is the point: an unlisted, unmatched path is a gap in
# BlenDiff, whereas these are inherent limits worth stating plainly.
UNSUPPORTED_REASONS: tuple[tuple[re.Pattern, str], ...] = (
	(re.compile(r"^type$"),
	 "An object's type cannot be changed after creation."),
	(re.compile(r"^visible_in_viewlayer$"),
	 "Derived from collection and object visibility; set those instead."),
	(re.compile(r'^armature\.bones\["' + QUOTED_NAME + r'"\]$'),
	 "BlenDiff cannot add or remove bones; edit the rig directly."),
	(re.compile(r"^armature\.(name|bone_count|collections)$"),
	 "Derived from the rig itself; change it in the armature."),
	(re.compile(r'^pose\.bones\["' + QUOTED_NAME + r'"\]\.constraints\[\d+\]\.type$'),
	 "Changing a constraint's type replaces it; re-create it manually."),
	(re.compile(r'^pose\.bones\["' + QUOTED_NAME + r'"\]\.constraints\[\d+\]$'),
	 "Adding or removing a bone constraint is not applicable; the snapshot "
	 "does not record its settings."),
	(re.compile(r'^pose\.bones\["' + QUOTED_NAME + r'"\]$'),
	 "BlenDiff cannot add or remove bones; edit the rig directly."),
	(re.compile(r"^pose\.bones\.[^.]+\.custom_shape$"),
	 "Custom shapes reference another object; assign it by hand."),
	(re.compile(r'^mesh\.shape_keys\["' + QUOTED_NAME + r'"\]\.shape$'),
	 "A shape key's points are hashed, not stored; sculpt it by hand."),
	(re.compile(r'^mesh\.shape_keys\["' + QUOTED_NAME + r'"\]\.(relative_key|vertex_group)$'),
	 "This shape key setting references other data; set it by hand."),
	(re.compile(r'^mesh\.shape_keys\["' + QUOTED_NAME + r'"\]$'),
	 "BlenDiff cannot add or remove shape keys; change them on the mesh."),
	(re.compile(r"^data\.(taper_object|bevel_object|font|sound)$"),
	 "This setting refers to another datablock; assign it by hand."),
	(re.compile(r"^mesh\."),
	 "Mesh geometry is summarised, not stored — BlenDiff cannot rebuild it."),
	(re.compile(r"^modifiers\[\d+\]\.type$"),
	 "Changing a modifier's type replaces it; re-create it manually."),
	(re.compile(r"^modifiers\[\d+\]\.node_group$"),
	 "Swapping a node group changes which inputs exist; assign it by hand."),
	(re.compile(r"^modifiers\[\d+\]$"),
	 "Adding or removing a modifier is not applicable; the snapshot does not "
	 "record its settings."),
	(re.compile(r"^constraints\[\d+\]\.type$"),
	 "Changing a constraint's type replaces it; re-create it manually."),
	(re.compile(r"^constraints\[\d+\]$"),
	 "Adding or removing a constraint is not applicable; the snapshot does "
	 "not record its settings."),
	(re.compile(r"^constraints?[\[.]"),
	 "This constraint change must be made by hand."),
	(re.compile(r"^fcurves?\."),
	 "Animation curves are summarised, not stored — keyframes cannot be rebuilt."),
	(re.compile(r'^drivers\["' + QUOTED_NAME + r'"\]\[\d+\]\.variables$'),
	 "The diff records only the variables' names, not their targets; set them "
	 "in the driver editor."),
	(re.compile(r'^drivers\["' + QUOTED_NAME + r'"\]\[\d+\]$'),
	 "Adding or removing a driver is not applicable; create it on the "
	 "property itself."),
	(re.compile(r"^drivers?[\[.]"),
	 "This driver change must be made by hand."),
	(re.compile(r"^nla"),
	 "NLA tracks are not yet applicable; re-create the strip manually."),
	(re.compile(_MATERIAL_NODE + r"\.type$"),
	 "Changing a node's type replaces it; swap the node by hand."),
	(re.compile(_MATERIAL_NODE + r"$"),
	 "Adding or removing a node is not applicable; the snapshot records its "
	 "type and inputs but not its own settings."),
	(re.compile(r'^materials\["' + QUOTED_NAME + r'"\]\.links$'),
	 "Rewiring a node graph is not applicable; connect the sockets by hand."),
	(re.compile(r'^materials\["' + QUOTED_NAME + r'"\]\.use_nodes$'),
	 "Turning nodes on or off replaces the whole graph; toggle it in the "
	 "material."),
	(re.compile(r"^materials?[\[.]"),
	 "This material change must be made by hand."),
	(re.compile(r"^scene\.world\.(hdri_filepath|hdri_strength)$"),
	 "An HDRI is an image datablock and a node to feed it; load it and plug "
	 "it in by hand."),
	(re.compile(r"^scene\.world\.use_nodes$"),
	 "Turning world nodes on or off replaces the whole graph; toggle it in "
	 "the world settings."),
	(re.compile(r"^scene\.world(\.name)?$"),
	 "Assigning a different world to the scene is not applicable; pick it in "
	 "the world settings."),
	(re.compile(r"^scene\."),
	 "This scene setting must be changed by hand."),
	(re.compile(r"^__add_add__$"),
	 "Both sides added an object with this name; BlenDiff cannot create objects."),
)


def find_applier(property_path: str) -> Optional[ApplierEntry]:
	"""Return the applier for a property path, or None when there is none."""
	for entry in REGISTRY:
		if entry.matches(property_path):
			return entry
	return None


def can_apply(property_path: str) -> bool:
	"""
	True when BlenDiff can actually write this property back to the scene.

	The merge UI uses this to mark unappliable conflicts read-only rather than
	inviting a resolution it would silently discard.
	"""
	return find_applier(property_path) is not None


def unsupported_reason(property_path: str) -> str:
	"""
	Explain why a property path cannot be applied.

	Always returns something usable: a specific reason for known limits, and a
	generic one otherwise, so the UI never has to render a blank explanation.
	"""
	for pattern, reason in UNSUPPORTED_REASONS:
		if pattern.match(property_path):
			return reason
	return "BlenDiff cannot apply this property automatically; change it by hand."


def describe(property_path: str) -> str:
	"""Human-readable name of what a property path affects."""
	entry = find_applier(property_path)
	if entry is not None:
		return entry.description
	return property_path


def apply_property(obj: Any, property_path: str, value: Any, context: Any) -> bool:
	"""
	Write one property back to a live Blender object.

	Returns True when applied, False when no applier covers the path. Writers
	raise on genuine failure so the caller can report it per property instead
	of silently dropping it.
	"""
	entry = find_applier(property_path)
	if entry is None:
		return False
	entry.writer(obj, property_path, value, context)
	return True
